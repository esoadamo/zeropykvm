import subprocess, time, ctypes

c_code = """
#include <stdint.h>
void convert_bgr24_to_rgb565(const uint8_t *src, uint8_t *dst, int width, int height, int stride) {
    for (int y = 0; y < height; y++) {
        const uint8_t *s = src + y * stride;
        uint16_t *d = (uint16_t *)(dst + y * width * 2);
        for (int x = 0; x < width; x++) {
            uint8_t b = s[x*3], g = s[x*3+1], r = s[x*3+2];
            d[x] = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
        }
    }
}
"""
with open('/tmp/conv.c', 'w') as f:
    f.write(c_code)
subprocess.run(['gcc', '-shared', '-fPIC', '-O3', '-o', '/tmp/conv.so', '/tmp/conv.c'], check=True)
lib = ctypes.CDLL('/tmp/conv.so')
data = bytes(1920*1080*3)
out = bytearray(1920*1080*2)
lib.convert_bgr24_to_rgb565.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]

out_ptr = (ctypes.c_char * len(out)).from_buffer(out)
t0 = time.time()
lib.convert_bgr24_to_rgb565(data, ctypes.byref(out_ptr), 1920, 1080, 1920*3)
print(f'Time: {time.time()-t0:.4f}s')
