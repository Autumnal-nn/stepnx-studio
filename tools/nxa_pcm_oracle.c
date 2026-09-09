/* Original research harness, Apache-2.0. Not linked into StepNX Studio.
 * Requires a separately installed libmad for local behavioral comparison.
 * NXA's observed caller synthesizes after success AND recoverable failure.
 * No implementation from libmad or the proprietary runtime is included here.
 */
#include <mad.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    FILE *input, *output, *log;
    unsigned char *bytes;
    long size;
    int exhausted = 0, failed = 0;
    struct mad_stream stream;
    struct mad_frame frame;
    struct mad_synth synth;
    if (argc != 4 || !strcmp(argv[1], argv[2]) || !strcmp(argv[1], argv[3])) return 2;
    input = fopen(argv[1], "rb");
    if (!input) return 3;
    if (fseek(input, 0, SEEK_END) || (size = ftell(input)) <= 0 || size > 64 * 1024 * 1024) {
        fclose(input); return 4;
    }
    rewind(input);
    bytes = calloc((size_t)size + MAD_BUFFER_GUARD, 1);
    if (!bytes || fread(bytes, 1, (size_t)size, input) != (size_t)size) {
        free(bytes); fclose(input); return 5;
    }
    fclose(input);
    output = fopen(argv[2], "wb");
    log = fopen(argv[3], "w");
    if (!output || !log) {
        if (output) fclose(output);
        if (log) fclose(log);
        free(bytes); return 6;
    }
    mad_stream_init(&stream);
    mad_frame_init(&frame);
    mad_synth_init(&synth);
    /* Guard storage exists, but the exposed stream length is the exact input
     * length, matching the observed caller. Do not count guard bytes as audio. */
    mad_stream_buffer(&stream, bytes, (unsigned long)size);
    fprintf(log, "offset,error,length,rate,nonzero\n");
    for (int iteration = 0; iteration < 100000; ++iteration) {
        int result = mad_frame_decode(&frame, &stream), nonzero = 0;
        if (result < 0 && !MAD_RECOVERABLE(stream.error)) {
            exhausted = 1; break;
        }
        mad_synth_frame(&synth, &frame);
        if (!synth.pcm.channels || synth.pcm.channels > 2) { failed = 1; break; }
        for (unsigned int i = 0; i < synth.pcm.length; ++i) {
            for (int channel = 0; channel < 2; ++channel) {
                int64_t value = (int64_t)synth.pcm.samples[channel % synth.pcm.channels][i] + 4096;
                int sample = value > 268435455 ? 32767 : value < -268435456 ? -32768 : (int)(value >> 13);
                unsigned int word = (unsigned int)sample;
                nonzero += sample != 0;
                fputc(word & 255, output);
                fputc((word >> 8) & 255, output);
            }
        }
        fprintf(log, "%ld,%d,%u,%u,%d\n", stream.this_frame ? (long)(stream.this_frame - bytes) : -1,
                result < 0 ? stream.error : 0, synth.pcm.length, synth.pcm.samplerate, nonzero);
    }
    mad_frame_finish(&frame);
    mad_stream_finish(&stream);
    free(bytes);
    failed |= ferror(output) || ferror(log) || !exhausted;
    failed |= fclose(output) != 0;
    failed |= fclose(log) != 0;
    return failed ? 7 : 0;
}
