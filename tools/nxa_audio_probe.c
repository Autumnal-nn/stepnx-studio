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
 * Captures the event order around libmad startup plus the exact byte buffers
 * handed to ALSA by snd_pcm_writei(). This is intended to distinguish actual
 * NXA output from a model inferred only from MP3 recovery errors.
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
static uint64_t capture_bytes = 0;
static uint64_t capture_limit = 64ULL * 1024ULL * 1024ULL;

#define MAX_HANDLES 32
struct dump_slot {
    snd_pcm_t *handle;
    int fd;
    unsigned long generation;
};
static struct dump_slot dumps[MAX_HANDLES];

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
    char path[1024];
    snprintf(path, sizeof(path), "%s/events.tsv", out_dir());
    log_fd = open(path, O_CREAT | O_WRONLY | O_APPEND, 0666);
    if (log_fd >= 0) {
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

static void close_dumps(void) {
    for (int i = 0; i < MAX_HANDLES; ++i) {
        if (dumps[i].fd >= 0) close(dumps[i].fd);
        dumps[i].handle = NULL;
        dumps[i].fd = -1;
        dumps[i].generation = 0;
    }
    capture_bytes = 0;
}

static struct dump_slot *dump_for(snd_pcm_t *handle) {
    struct dump_slot *free_slot = NULL;
    for (int i = 0; i < MAX_HANDLES; ++i) {
        if (dumps[i].handle == handle && dumps[i].generation == generation)
            return &dumps[i];
        if (!free_slot && dumps[i].handle == NULL) free_slot = &dumps[i];
    }
    if (!free_slot) return NULL;
    char path[1024];
    snprintf(path, sizeof(path), "%s/pcm-gen%03lu-handle-%p.raw",
             out_dir(), generation, (void *)handle);
    int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0666);
    if (fd < 0) return NULL;
    free_slot->handle = handle;
    free_slot->fd = fd;
    free_slot->generation = generation;
    return free_slot;
}

__attribute__((constructor))
static void init_probe(void) {
    for (int i = 0; i < MAX_HANDLES; ++i) dumps[i].fd = -1;
    event("probe_init", 0, NULL, 0, 0, "loaded");
}

__attribute__((destructor))
static void finish_probe(void) {
    pthread_mutex_lock(&lock);
    close_dumps();
    if (log_fd >= 0) close(log_fd);
    log_fd = -1;
    pthread_mutex_unlock(&lock);
}

void mad_stream_init(mad_stream_t *stream) {
    static mad_stream_init_fn real_fn;
    if (!real_fn) real_fn = (mad_stream_init_fn)dlsym(RTLD_NEXT, "mad_stream_init");
    if (real_fn) real_fn(stream);
    pthread_mutex_lock(&lock);
    ++generation;
    decode_seq = synth_seq = write_seq = 0;
    close_dumps();
    pthread_mutex_unlock(&lock);
    event("mad_stream_init", 0, stream, 0, 0, "new stream");
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
    pthread_mutex_lock(&lock); seq = ++decode_seq; pthread_mutex_unlock(&lock);
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
    pthread_mutex_lock(&lock); seq = ++synth_seq; pthread_mutex_unlock(&lock);
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
    event("snd_pcm_open", 0, (rc == 0 && pcm) ? *pcm : NULL, rc, stream,
          name ? name : "");
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
    return rc;
}

snd_pcm_sframes_t snd_pcm_writei(snd_pcm_t *pcm, const void *buffer,
                                 snd_pcm_uframes_t frames) {
    static snd_pcm_writei_fn real_fn;
    static snd_pcm_frames_to_bytes_fn bytes_fn;
    if (!real_fn) real_fn = (snd_pcm_writei_fn)dlsym(RTLD_NEXT, "snd_pcm_writei");
    if (!bytes_fn) bytes_fn = (snd_pcm_frames_to_bytes_fn)dlsym(RTLD_NEXT, "snd_pcm_frames_to_bytes");
    unsigned long seq;
    long byte_count = bytes_fn ? bytes_fn(pcm, (snd_pcm_sframes_t)frames) : -1;

    pthread_mutex_lock(&lock);
    seq = ++write_seq;
    if (buffer && byte_count > 0 && capture_bytes < capture_limit) {
        uint64_t remaining = capture_limit - capture_bytes;
        size_t count = (uint64_t)byte_count < remaining ? (size_t)byte_count : (size_t)remaining;
        struct dump_slot *slot = dump_for(pcm);
        if (slot && slot->fd >= 0 && count) {
            ssize_t written = write(slot->fd, buffer, count);
            if (written > 0) capture_bytes += (uint64_t)written;
        }
    }
    pthread_mutex_unlock(&lock);

    event("snd_pcm_writei_enter", seq, pcm, (long long)frames, byte_count, "");
    snd_pcm_sframes_t rc = real_fn ? real_fn(pcm, buffer, frames) : -1;
    event("snd_pcm_writei_leave", seq, pcm, (long long)rc, (long long)frames, "");
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
