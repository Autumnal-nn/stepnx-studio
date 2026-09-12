#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

/*
 * Passive LD_PRELOAD probe for the 32-bit NXA runtime.
 *
 * No libmad/ALSA development headers are needed. Types stay opaque and every
 * intercepted call is forwarded unchanged via RTLD_NEXT.
 *
 * The ALSA capture is continuous for each snd_pcm_t handle lifetime. It is
 * deliberately NOT split at mad_stream_init(): decoder stream boundaries and
 * the audio-output thread are asynchronous, and splitting there can assign
 * already-queued PCM to the next libmad generation. Each stream init records
 * the current accepted-PCM cursor instead.
 *
 * snd_pcm_writei() buffers are copied only after the real call returns, and
 * only the frames ALSA actually accepted are stored. This avoids recording
 * partial/error writes as if they had reached the device.
 *
 * For mad_synth_frame(), the probe also reads the public libmad ABI layout of
 * struct mad_synth after the real call and records pcm.length, samplerate,
 * channels, first non-zero sample and peak fixed-point magnitude. This is
 * observation only; no libmad state is modified.
 */

typedef void mad_stream_t;
typedef void mad_frame_t;
typedef void mad_synth_t;
typedef void snd_pcm_t;
typedef long snd_pcm_sframes_t;
typedef unsigned long snd_pcm_uframes_t;

typedef void (*mad_stream_init_fn)(mad_stream_t *);
typedef void (*mad_stream_buffer_fn)(mad_stream_t *, const unsigned char *, unsigned long);
typedef int (*mad_frame_decode_fn)(mad_frame_t *, mad_stream_t *);
typedef const char *(*mad_stream_errorstr_fn)(const mad_stream_t *);
typedef void (*mad_synth_frame_fn)(mad_synth_t *, const mad_frame_t *);
typedef int (*snd_pcm_open_fn)(snd_pcm_t **, const char *, int, int);
typedef int (*snd_pcm_close_fn)(snd_pcm_t *);
typedef int (*snd_pcm_prepare_fn)(snd_pcm_t *);
typedef int (*snd_pcm_drop_fn)(snd_pcm_t *);
typedef snd_pcm_sframes_t (*snd_pcm_writei_fn)(snd_pcm_t *, const void *, snd_pcm_uframes_t);
typedef int (*snd_pcm_delay_fn)(snd_pcm_t *, snd_pcm_sframes_t *);
typedef long (*snd_pcm_frames_to_bytes_fn)(snd_pcm_t *, snd_pcm_sframes_t);

/*
 * libmad ABI subset used only for read-only observation after mad_synth_frame.
 * On the 32-bit NXA target mad_fixed_t is a 32-bit signed long, represented
 * here as int32_t so the layout is independent of the host compiler's long.
 */
struct probe_mad_pcm {
    unsigned int samplerate;
    unsigned short channels;
    unsigned short length;
    int32_t samples[2][1152];
};

struct probe_mad_synth {
    int32_t filter[2][2][2][16][8];
    unsigned int phase;
    struct probe_mad_pcm pcm;
};

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static int log_fd = -1;
static unsigned long generation = 0;
static unsigned long decode_seq = 0;
static unsigned long synth_seq = 0;
static unsigned long write_seq = 0;
static unsigned long pcm_open_seq = 0;
static uint64_t capture_bytes = 0;
static uint64_t capture_limit = 64ULL * 1024ULL * 1024ULL;

#define MAX_HANDLES 32
struct dump_slot {
    snd_pcm_t *handle;
    int fd;
    unsigned long open_seq;
    uint64_t frames_accepted;
    uint64_t bytes_captured;
};
static struct dump_slot dumps[MAX_HANDLES];

struct cursor_snapshot {
    snd_pcm_t *handle;
    unsigned long open_seq;
    uint64_t frames_accepted;
    uint64_t bytes_captured;
};

static long tid_now(void) {
    return (long)syscall(SYS_gettid);
}

static uint64_t mono_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static const char *out_dir(void) {
    const char *p = getenv("NXA_AUDIO_PROBE_DIR");
    return (p && *p) ? p : "/tmp/nxa-audio-probe";
}

static void ensure_log(void) {
    if (log_fd >= 0) return;
    mkdir(out_dir(), 0777);
    (void)chmod(out_dir(), 0777);
    char path[1024];
    snprintf(path, sizeof(path), "%s/events.tsv", out_dir());
    log_fd = open(path, O_CREAT | O_WRONLY | O_APPEND, 0666);
    if (log_fd >= 0) {
        (void)fchmod(log_fd, 0644);
        const char *h = "mono_ns\ttid\tgeneration\tevent\tseq\tobject\targ0\targ1\tdetail\n";
        (void)write(log_fd, h, strlen(h));
    }
    const char *mb = getenv("NXA_AUDIO_PROBE_MAX_MB");
    if (mb && *mb) {
        unsigned long value = strtoul(mb, NULL, 10);
        if (value) capture_limit = (uint64_t)value * 1024ULL * 1024ULL;
    }
}

static void event(const char *name, unsigned long seq, const void *object,
                  long long arg0, long long arg1, const char *detail) {
    pthread_mutex_lock(&lock);
    ensure_log();
    if (log_fd >= 0) {
        char line[2048];
        int n = snprintf(line, sizeof(line),
            "%llu\t%ld\t%lu\t%s\t%lu\t%p\t%lld\t%lld\t%s\n",
            (unsigned long long)mono_ns(), tid_now(), generation, name, seq,
            object, arg0, arg1, detail ? detail : "");
        if (n > 0) (void)write(log_fd, line, (size_t)n);
    }
    pthread_mutex_unlock(&lock);
}

static void close_slot_locked(struct dump_slot *slot) {
    if (!slot) return;
    if (slot->fd >= 0) close(slot->fd);
    slot->handle = NULL;
    slot->fd = -1;
    slot->open_seq = 0;
    slot->frames_accepted = 0;
    slot->bytes_captured = 0;
}

static void close_dumps_locked(void) {
    for (int i = 0; i < MAX_HANDLES; ++i) close_slot_locked(&dumps[i]);
}

static struct dump_slot *find_slot_locked(snd_pcm_t *handle) {
    for (int i = 0; i < MAX_HANDLES; ++i) {
        if (dumps[i].handle == handle) return &dumps[i];
    }
    return NULL;
}

static struct dump_slot *register_slot_locked(snd_pcm_t *handle) {
    struct dump_slot *slot = find_slot_locked(handle);
    if (slot) return slot;

    for (int i = 0; i < MAX_HANDLES; ++i) {
        if (dumps[i].handle != NULL) continue;

        char path[1024];
        unsigned long open_seq = ++pcm_open_seq;
        snprintf(path, sizeof(path), "%s/pcm-open%03lu-handle-%p.raw",
                 out_dir(), open_seq, (void *)handle);
        int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0666);
        if (fd < 0) return NULL;
        (void)fchmod(fd, 0644);

        dumps[i].handle = handle;
        dumps[i].fd = fd;
        dumps[i].open_seq = open_seq;
        dumps[i].frames_accepted = 0;
        dumps[i].bytes_captured = 0;
        return &dumps[i];
    }
    return NULL;
}

__attribute__((constructor))
static void init_probe(void) {
    for (int i = 0; i < MAX_HANDLES; ++i) dumps[i].fd = -1;
    event("probe_init", 0, NULL, 0, 0, "loaded");
}

__attribute__((destructor))
static void finish_probe(void) {
    pthread_mutex_lock(&lock);
    close_dumps_locked();
    if (log_fd >= 0) close(log_fd);
    log_fd = -1;
    pthread_mutex_unlock(&lock);
}

void mad_stream_init(mad_stream_t *stream) {
    static mad_stream_init_fn real_fn;
    if (!real_fn) real_fn = (mad_stream_init_fn)dlsym(RTLD_NEXT, "mad_stream_init");
    if (real_fn) real_fn(stream);

    struct cursor_snapshot snapshots[MAX_HANDLES];
    int snapshot_count = 0;

    pthread_mutex_lock(&lock);
    ++generation;
    decode_seq = 0;
    synth_seq = 0;
    write_seq = 0;
    for (int i = 0; i < MAX_HANDLES; ++i) {
        if (!dumps[i].handle) continue;
        snapshots[snapshot_count].handle = dumps[i].handle;
        snapshots[snapshot_count].open_seq = dumps[i].open_seq;
        snapshots[snapshot_count].frames_accepted = dumps[i].frames_accepted;
        snapshots[snapshot_count].bytes_captured = dumps[i].bytes_captured;
        ++snapshot_count;
    }
    pthread_mutex_unlock(&lock);

    event("mad_stream_init", 0, stream, 0, 0, "new stream");
    for (int i = 0; i < snapshot_count; ++i) {
        char detail[96];
        snprintf(detail, sizeof(detail), "open_seq=%lu bytes_captured=%llu",
                 snapshots[i].open_seq,
                 (unsigned long long)snapshots[i].bytes_captured);
        event("pcm_cursor_at_stream_init", 0, snapshots[i].handle,
              (long long)snapshots[i].frames_accepted,
              (long long)snapshots[i].open_seq,
              detail);
    }
}

void mad_stream_buffer(mad_stream_t *stream, const unsigned char *buffer,
                       unsigned long length) {
    static mad_stream_buffer_fn real_fn;
    if (!real_fn) real_fn = (mad_stream_buffer_fn)dlsym(RTLD_NEXT, "mad_stream_buffer");
    event("mad_stream_buffer", 0, stream, (long long)length,
          (long long)(uintptr_t)buffer, "");
    if (real_fn) real_fn(stream, buffer, length);
}

int mad_frame_decode(mad_frame_t *frame, mad_stream_t *stream) {
    static mad_frame_decode_fn real_fn;
    static mad_stream_errorstr_fn errorstr_fn;
    if (!real_fn) real_fn = (mad_frame_decode_fn)dlsym(RTLD_NEXT, "mad_frame_decode");
    if (!errorstr_fn) errorstr_fn = (mad_stream_errorstr_fn)dlsym(RTLD_NEXT, "mad_stream_errorstr");
    unsigned long seq;
    pthread_mutex_lock(&lock);
    seq = ++decode_seq;
    pthread_mutex_unlock(&lock);

    int rc = real_fn ? real_fn(frame, stream) : -1;
    const char *detail = "";
    if (rc != 0 && errorstr_fn) {
        const char *text = errorstr_fn(stream);
        if (text) detail = text;
    }
    event("mad_frame_decode", seq, stream, rc, 0, detail);
    return rc;
}

void mad_synth_frame(mad_synth_t *synth, const mad_frame_t *frame) {
    static mad_synth_frame_fn real_fn;
    if (!real_fn) real_fn = (mad_synth_frame_fn)dlsym(RTLD_NEXT, "mad_synth_frame");
    unsigned long seq;
    pthread_mutex_lock(&lock);
    seq = ++synth_seq;
    pthread_mutex_unlock(&lock);

    event("mad_synth_enter", seq, synth, 0, 0, "");
    if (real_fn) real_fn(synth, frame);

    const struct probe_mad_synth *observed = (const struct probe_mad_synth *)synth;
    unsigned int raw_length = observed->pcm.length;
    unsigned int scan_length = raw_length <= 1152U ? raw_length : 1152U;
    unsigned int channels = observed->pcm.channels;
    unsigned int scan_channels = channels <= 2U ? channels : 2U;
    long first_nonzero = -1;
    int64_t peak = 0;

    for (unsigned int i = 0; i < scan_length; ++i) {
        for (unsigned int ch = 0; ch < scan_channels; ++ch) {
            int64_t value = observed->pcm.samples[ch][i];
            int64_t magnitude = value < 0 ? -value : value;
            if (value != 0 && first_nonzero < 0) first_nonzero = (long)i;
            if (magnitude > peak) peak = magnitude;
        }
    }

    char detail[160];
    snprintf(detail, sizeof(detail),
             "channels=%u first_nonzero=%ld peak=%lld",
             channels, first_nonzero, (long long)peak);
    event("mad_synth_pcm", seq, synth,
          (long long)raw_length,
          (long long)observed->pcm.samplerate,
          detail);
    event("mad_synth_leave", seq, synth, 0, 0, "");
}

int snd_pcm_open(snd_pcm_t **pcm, const char *name, int stream, int mode) {
    static snd_pcm_open_fn real_fn;
    if (!real_fn) real_fn = (snd_pcm_open_fn)dlsym(RTLD_NEXT, "snd_pcm_open");
    int rc = real_fn ? real_fn(pcm, name, stream, mode) : -1;

    snd_pcm_t *handle = (rc == 0 && pcm) ? *pcm : NULL;
    unsigned long open_seq = 0;
    if (handle) {
        pthread_mutex_lock(&lock);
        struct dump_slot *slot = register_slot_locked(handle);
        if (slot) open_seq = slot->open_seq;
        pthread_mutex_unlock(&lock);
    }

    char detail[256];
    snprintf(detail, sizeof(detail), "%s open_seq=%lu", name ? name : "", open_seq);
    event("snd_pcm_open", 0, handle, rc, stream, detail);
    return rc;
}

int snd_pcm_prepare(snd_pcm_t *pcm) {
    static snd_pcm_prepare_fn real_fn;
    if (!real_fn) real_fn = (snd_pcm_prepare_fn)dlsym(RTLD_NEXT, "snd_pcm_prepare");
    int rc = real_fn ? real_fn(pcm) : -1;
    event("snd_pcm_prepare", 0, pcm, rc, 0, "");
    return rc;
}

int snd_pcm_drop(snd_pcm_t *pcm) {
    static snd_pcm_drop_fn real_fn;
    if (!real_fn) real_fn = (snd_pcm_drop_fn)dlsym(RTLD_NEXT, "snd_pcm_drop");
    int rc = real_fn ? real_fn(pcm) : -1;
    event("snd_pcm_drop", 0, pcm, rc, 0, "");
    return rc;
}

int snd_pcm_close(snd_pcm_t *pcm) {
    static snd_pcm_close_fn real_fn;
    if (!real_fn) real_fn = (snd_pcm_close_fn)dlsym(RTLD_NEXT, "snd_pcm_close");
    event("snd_pcm_close_enter", 0, pcm, 0, 0, "");
    int rc = real_fn ? real_fn(pcm) : -1;
    event("snd_pcm_close_leave", 0, pcm, rc, 0, "");

    pthread_mutex_lock(&lock);
    struct dump_slot *slot = find_slot_locked(pcm);
    if (slot) close_slot_locked(slot);
    pthread_mutex_unlock(&lock);
    return rc;
}

snd_pcm_sframes_t snd_pcm_writei(snd_pcm_t *pcm, const void *buffer,
                                 snd_pcm_uframes_t frames) {
    static snd_pcm_writei_fn real_fn;
    static snd_pcm_frames_to_bytes_fn bytes_fn;
    if (!real_fn) real_fn = (snd_pcm_writei_fn)dlsym(RTLD_NEXT, "snd_pcm_writei");
    if (!bytes_fn) bytes_fn = (snd_pcm_frames_to_bytes_fn)dlsym(RTLD_NEXT, "snd_pcm_frames_to_bytes");

    unsigned long seq;
    pthread_mutex_lock(&lock);
    seq = ++write_seq;
    pthread_mutex_unlock(&lock);

    long requested_bytes = bytes_fn ? bytes_fn(pcm, (snd_pcm_sframes_t)frames) : -1;
    event("snd_pcm_writei_enter", seq, pcm, (long long)frames, requested_bytes, "");

    snd_pcm_sframes_t rc = real_fn ? real_fn(pcm, buffer, frames) : -1;

    uint64_t pcm_start = 0;
    uint64_t pcm_end = 0;
    long accepted_bytes = -1;
    ssize_t captured_now = 0;
    unsigned long open_seq = 0;

    if (rc > 0) {
        accepted_bytes = bytes_fn ? bytes_fn(pcm, rc) : -1;

        pthread_mutex_lock(&lock);
        struct dump_slot *slot = find_slot_locked(pcm);
        if (!slot) slot = register_slot_locked(pcm);
        if (slot) {
            open_seq = slot->open_seq;
            pcm_start = slot->frames_accepted;
            slot->frames_accepted += (uint64_t)rc;
            pcm_end = slot->frames_accepted;

            if (buffer && accepted_bytes > 0 && capture_bytes < capture_limit) {
                uint64_t remaining = capture_limit - capture_bytes;
                size_t count = (uint64_t)accepted_bytes < remaining
                    ? (size_t)accepted_bytes : (size_t)remaining;
                if (slot->fd >= 0 && count) {
                    captured_now = write(slot->fd, buffer, count);
                    if (captured_now > 0) {
                        slot->bytes_captured += (uint64_t)captured_now;
                        capture_bytes += (uint64_t)captured_now;
                    }
                }
            }
        }
        pthread_mutex_unlock(&lock);
    }

    char detail[192];
    snprintf(detail, sizeof(detail),
             "open_seq=%lu pcm_start=%llu pcm_end=%llu accepted_bytes=%ld captured_bytes=%ld",
             open_seq,
             (unsigned long long)pcm_start,
             (unsigned long long)pcm_end,
             accepted_bytes,
             (long)captured_now);
    event("snd_pcm_writei_leave", seq, pcm, (long long)rc, (long long)frames, detail);
    return rc;
}

int snd_pcm_delay(snd_pcm_t *pcm, snd_pcm_sframes_t *delayp) {
    static snd_pcm_delay_fn real_fn;
    if (!real_fn) real_fn = (snd_pcm_delay_fn)dlsym(RTLD_NEXT, "snd_pcm_delay");
    int rc = real_fn ? real_fn(pcm, delayp) : -1;
    long long delay = (rc == 0 && delayp) ? (long long)*delayp : 0;
    event("snd_pcm_delay", 0, pcm, rc, delay, "");
    return rc;
}
