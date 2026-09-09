/* StepNX frame-indexed PCM bridge. Original bridge code: Apache-2.0.
 * The separately attributed decoder is minimp3, CC0-1.0.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <limits.h>
#include <string.h>
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

static PyMethodDef methods[] = {
    {"decode", decode, METH_VARARGS, "Decode an exact Layer III frame chain, preserving every frame's duration."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_mpeg_pcm", NULL, -1, methods};
PyMODINIT_FUNC PyInit__mpeg_pcm(void) { return PyModule_Create(&module); }
