/* StepNX frame-indexed PCM bridge. Original bridge code: Apache-2.0.
 * The separately attributed decoder is minimp3, CC0-1.0.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <limits.h>
#include <string.h>
#include <stdint.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "_vendor/minimp3/minimp3.h"

static PyObject *decode(PyObject *self, PyObject *args)
{
    const unsigned char *input;
    Py_ssize_t size, expected, offset = 0, written = 0;
    mp3dec_t decoder;
    mp3dec_frame_info_t info;
    mp3d_sample_t frame[MINIMP3_MAX_SAMPLES_PER_FRAME];
    PyObject *output, *missing;
    int rate = 0, channels = 0;
    (void)self;
    if (!PyArg_ParseTuple(args, "y#n", &input, &size, &expected)) return NULL;
    if (size > INT_MAX || expected <= 0 || expected > 128000000) {
        PyErr_SetString(PyExc_ValueError, "MPEG PCM size exceeds the decode limit");
        return NULL;
    }
    output = PyBytes_FromStringAndSize(NULL, expected * 4);
    missing = PyList_New(0);
    if (!output || !missing) { Py_XDECREF(output); Py_XDECREF(missing); return NULL; }
    memset(&decoder, 0, sizeof(decoder));
    mp3dec_init(&decoder);
    while (offset < size) {
        int count, nominal, i;
        Py_ssize_t before = offset;
        memset(&info, 0, sizeof(info));
        Py_BEGIN_ALLOW_THREADS
        count = mp3dec_decode_frame(&decoder, input + offset, (int)(size - offset), frame, &info);
        Py_END_ALLOW_THREADS
        if (info.frame_bytes <= 0 || info.frame_offset != 0 || info.layer != 3 ||
            (info.channels != 1 && info.channels != 2)) {
            PyErr_SetString(PyExc_ValueError, "decoder lost the validated MPEG frame boundary");
            goto fail;
        }
        if (!rate) { rate = info.hz; channels = info.channels; }
        if (rate != info.hz || channels != info.channels) {
            PyErr_SetString(PyExc_ValueError, "MPEG format changed during PCM decoding");
            goto fail;
        }
        nominal = ((input[offset + 1] >> 3) & 3) == 3 ? 1152 : 576;
        if (written + nominal > expected || (count != 0 && count != nominal)) {
            PyErr_SetString(PyExc_ValueError, "decoder output disagrees with the MPEG sample ledger");
            goto fail;
        }
        if (!count) {
            PyObject *item = PyLong_FromSsize_t(before);
            if (!item || PyList_Append(missing, item) < 0) { Py_XDECREF(item); goto fail; }
            Py_DECREF(item);
            memset(frame, 0, sizeof(frame));
        }
        /* A fixed stereo S16LE wire format, including on big-endian hosts.
         * Mono duplication matches the observed NXA mixer path. */
        for (i = 0; i < nominal; ++i) {
            unsigned short left = (unsigned short)frame[i * channels];
            unsigned short right = (unsigned short)frame[i * channels + channels - 1];
            unsigned char *out = (unsigned char *)PyBytes_AS_STRING(output) + (written + i) * 4;
            out[0] = (unsigned char)left; out[1] = (unsigned char)(left >> 8);
            out[2] = (unsigned char)right; out[3] = (unsigned char)(right >> 8);
        }
        written += nominal;
        offset += info.frame_bytes;
        if (PyErr_CheckSignals() < 0) goto fail;
    }
    if (written != expected || offset != size) {
        PyErr_SetString(PyExc_ValueError, "incomplete MPEG PCM decode");
        goto fail;
    }
    return Py_BuildValue("NNii", output, missing, rate, channels);
fail:
    Py_DECREF(output); Py_DECREF(missing);
    return NULL;
}

static PyObject *mix_clicks(PyObject *self, PyObject *args)
{
    const unsigned char *input;
    Py_ssize_t size, count, click_size, length, click_frames, i, first = 0, begin = 0;
    PyObject *click_arg, *events_arg, *click = NULL, *events = NULL, *output = NULL;
    int16_t *sound = NULL;
    Py_ssize_t *positions = NULL;
    int64_t *work = NULL;
    unsigned char *out;
    (void)self;
    if (!PyArg_ParseTuple(args, "y#OO", &input, &size, &click_arg, &events_arg)) return NULL;
    if (size % 4 || size / 4 > 128000000) {
        PyErr_SetString(PyExc_ValueError, "invalid stereo PCM length"); return NULL;
    }
    click = PySequence_Fast(click_arg, "click must be a sequence");
    events = PySequence_Fast(events_arg, "events must be a sequence");
    if (!click || !events) goto done;
    click_size = PySequence_Fast_GET_SIZE(click);
    count = PySequence_Fast_GET_SIZE(events);
    length = size / 4;
    click_frames = click_size / 2;
    if (click_size % 2 || click_size > 256000000 || count > 1000000) {
        PyErr_SetString(PyExc_ValueError, "invalid or excessive click schedule"); goto done;
    }
    sound = PyMem_Malloc((size_t)(click_size ? click_size : 1) * sizeof(*sound));
    positions = PyMem_Malloc((size_t)(count ? count : 1) * sizeof(*positions));
    work = PyMem_Malloc(8192 * 2 * sizeof(*work));
    if (!sound || !positions || !work) { PyErr_NoMemory(); goto done; }
    for (i = 0; i < click_size; ++i) {
        long value = PyLong_AsLong(PySequence_Fast_GET_ITEM(click, i));
        if (PyErr_Occurred()) goto done;
        if (value < -32768 || value > 32767) {
            PyErr_SetString(PyExc_ValueError, "click samples must be S16"); goto done;
        }
        sound[i] = (int16_t)value;
    }
    for (i = 0; i < count; ++i) {
        positions[i] = PyLong_AsSsize_t(PySequence_Fast_GET_ITEM(events, i));
        if (PyErr_Occurred()) goto done;
        if (positions[i] <= -click_frames || positions[i] >= length ||
            (i && positions[i] <= positions[i - 1])) {
            PyErr_SetString(PyExc_ValueError, "events must be sorted, unique and overlap the music"); goto done;
        }
    }
    output = PyBytes_FromStringAndSize((const char *)input, size);
    if (!output) goto done;
    out = (unsigned char *)PyBytes_AS_STRING(output);
    /* Bounded scratch space and one final saturation, even with overlapping
     * opposite-sign clicks. Explicit LE reads/writes avoid host endianness.
     * The immutable inputs stay owned by args while the GIL is released. */
    Py_BEGIN_ALLOW_THREADS
    while (first < count && begin < length) {
        Py_ssize_t end, j, p;
        if (begin < positions[first]) begin = positions[first];
        end = begin + 8192;
        if (end > length) end = length;
        for (p = begin * 2; p < end * 2; ++p) {
            int value = input[p * 2] | ((int)input[p * 2 + 1] << 8);
            work[p - begin * 2] = value >= 32768 ? value - 65536 : value;
        }
        for (j = first; j < count && positions[j] < end; ++j) {
            Py_ssize_t low = positions[j] > begin ? positions[j] : begin;
            Py_ssize_t high = positions[j] + click_frames;
            if (high > end) high = end;
            for (p = low * 2; p < high * 2; ++p)
                work[p - begin * 2] += sound[p - positions[j] * 2];
        }
        for (p = begin * 2; p < end * 2; ++p) {
            int64_t value = work[p - begin * 2];
            unsigned short sample;
            if (value < -32768) value = -32768;
            if (value > 32767) value = 32767;
            sample = (unsigned short)value;
            out[p * 2] = (unsigned char)sample;
            out[p * 2 + 1] = (unsigned char)(sample >> 8);
        }
        begin = end;
        while (first < count && positions[first] + click_frames <= begin) ++first;
    }
    Py_END_ALLOW_THREADS
    if (PyErr_CheckSignals() < 0) { Py_CLEAR(output); }
done:
    Py_XDECREF(click); Py_XDECREF(events);
    PyMem_Free(sound); PyMem_Free(positions); PyMem_Free(work);
    return output;
}

static PyMethodDef methods[] = {
    {"decode", decode, METH_VARARGS, "Decode an exact Layer III frame chain, preserving every frame's duration."},
    {"mix_clicks", mix_clicks, METH_VARARGS, "Mix sample-indexed S16 clicks with bounded scratch space."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_mpeg_pcm", NULL, -1, methods};
PyMODINIT_FUNC PyInit__mpeg_pcm(void) { return PyModule_Create(&module); }
