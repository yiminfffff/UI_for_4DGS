"""Fetch only bouncingballs from the official D-NeRF ZIP using HTTP ranges."""
import io
import struct
import zipfile
from pathlib import Path
import requests

URL = 'https://dl.dropboxusercontent.com/s/0bf6fl0ye2vz3vr/data.zip'

def fetch(start, end):
    r = requests.get(URL, headers={'Range': f'bytes={start}-{end}'}, timeout=120)
    r.raise_for_status()
    if r.status_code != 206 or len(r.content) != end - start + 1:
        raise RuntimeError(f'Unexpected range response: {r.status_code}, {r.headers.get("Content-Range")}')
    return r.content

if __name__ == '__main__':
    probe = requests.get(URL, headers={'Range': 'bytes=0-0'}, timeout=60)
    probe.raise_for_status()
    size = int(probe.headers['Content-Range'].split('/')[-1])
    tail_start = max(0, size - 65557)
    tail = fetch(tail_start, size - 1)
    eocd = tail.rfind(b'PK\x05\x06')
    fields = struct.unpack_from('<4s4H2LH', tail, eocd)
    cd_size, cd_start = fields[5:7]
    central = fetch(cd_start, cd_start + cd_size - 1)
    # A local metadata-only ZIP retains the original offsets in ZipInfo.
    meta = bytearray(tail[eocd:])
    struct.pack_into('<L', meta, 16, 0)
    z = zipfile.ZipFile(io.BytesIO(central + meta))
    selected = [i for i in z.infolist() if '/bouncingballs/' in '/' + i.filename and not i.is_dir()]
    print(f'Archive {size:,} bytes; bouncingballs: {len(selected)} files', flush=True)
    if not selected:
        raise RuntimeError('No bouncingballs files found')
    first = min(i.header_offset for i in selected)
    last = max(i.header_offset + 30 + len(i.filename.encode()) + len(i.extra) + i.compress_size + 1024 for i in selected)
    last = min(last, cd_start)
    print(f'Downloading selected ZIP span: {last-first:,} bytes', flush=True)
    data = fetch(first, last - 1)
    out = Path(__file__).resolve().parent / 'HUST-Windows/data/dnerf/bouncingballs'
    import zlib
    for info in selected:
        offset = info.header_offset - first
        header = struct.unpack_from('<4s5H3L2H', data, offset)
        begin = offset + 30 + header[-2] + header[-1]
        payload = data[begin:begin + info.compress_size]
        decoded = zlib.decompress(payload, -15) if info.compress_type == 8 else payload
        if len(decoded) != info.file_size or zlib.crc32(decoded) & 0xffffffff != info.CRC:
            raise RuntimeError(f'CRC mismatch: {info.filename}')
        relative = info.filename.split('bouncingballs/', 1)[1]
        target = (out / relative).resolve()
        if not target.is_relative_to(out.resolve()):
            raise RuntimeError('Unsafe archive path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(decoded)
    print(f'Extracted and CRC-verified {len(selected)} files to {out}', flush=True)
