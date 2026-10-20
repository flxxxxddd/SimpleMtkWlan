from pathlib import Path
import re
import subprocess
import sys
import tempfile

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / 'mtk80211/compat.cpp'
s = src.read_text()
start = s.index('IOBufferMemoryDescriptor* alloc_dma_memory(', s.index('IOBufferMemoryDescriptor* alloc_dma_memory(') + 1)
allocator = s[start:s.index('\nint bus_dmamem_alloc(', start)]
bounce_call = re.search(r'alloc_dma_memory\(bounce_size, PAGE_SIZE,?.*?\);', s, re.S).group(0)
ring_call = re.search(r'alloc_dma_memory\(size, alignment\);', s).group(0)
stub = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
using mach_vm_address_t = uint64_t;
using IOOptionBits = unsigned;
constexpr unsigned kIOMemoryPhysicallyContiguous = 0x10;
constexpr unsigned kIOMapInhibitCache = 0x100;
constexpr unsigned kIOMapDefaultCache = 0;
constexpr unsigned PAGE_SIZE = 4096;
constexpr int kernel_task = 1;
struct IOBufferMemoryDescriptor {
    static unsigned seen_options;
    static uint64_t seen_mask;
    static size_t seen_size;
    static int preparations;
    static bool fail;
    static IOBufferMemoryDescriptor* inTaskWithPhysicalMask(int task, unsigned opts, size_t size, uint64_t mask) {
        assert(task == kernel_task);
        seen_options = opts; seen_size = size; seen_mask = mask;
        static IOBufferMemoryDescriptor allocation;
        return fail ? nullptr : &allocation;
    }
    void prepare() { ++preparations; }
};
unsigned IOBufferMemoryDescriptor::seen_options;
uint64_t IOBufferMemoryDescriptor::seen_mask;
size_t IOBufferMemoryDescriptor::seen_size;
int IOBufferMemoryDescriptor::preparations;
bool IOBufferMemoryDescriptor::fail;
'''
main = r'''
int main() {
    for (size_t bounce_size : {size_t(2048), size_t(4096), size_t(8192)}) {
        auto* packet = BOUNCE_CALL
        assert(packet);
        assert(IOBufferMemoryDescriptor::seen_options == (kIOMemoryPhysicallyContiguous | kIOMapDefaultCache));
        assert(IOBufferMemoryDescriptor::seen_size == bounce_size);
        assert(IOBufferMemoryDescriptor::seen_mask == 0xfffff000ULL);
        size_t size = bounce_size;
        mach_vm_address_t alignment = PAGE_SIZE;
        auto* ring = RING_CALL
        assert(ring);
        assert(IOBufferMemoryDescriptor::seen_options == (kIOMemoryPhysicallyContiguous | kIOMapInhibitCache));
        assert(IOBufferMemoryDescriptor::seen_size == size);
        assert(IOBufferMemoryDescriptor::seen_mask == 0xfffff000ULL);
    }
    assert(IOBufferMemoryDescriptor::preparations == 6);
    IOBufferMemoryDescriptor::fail = true;
    size_t bounce_size = 4096;
    assert((BOUNCE_EXPR) == nullptr);
    assert(IOBufferMemoryDescriptor::preparations == 6);
}
'''.replace('BOUNCE_CALL', bounce_call).replace('RING_CALL', ring_call).replace('BOUNCE_EXPR', bounce_call[:-1])
with tempfile.TemporaryDirectory(prefix='mtk-dma-test-') as tmp:
    cpp = Path(tmp) / 'cache.cpp'
    exe = Path(tmp) / 'cache-test'
    cpp.write_text(stub + allocator + main)
    subprocess.run(['clang++', '-std=c++14', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: cached packet bounce allocation, uncached descriptor allocation, physical mask, preparation and null allocation.')
