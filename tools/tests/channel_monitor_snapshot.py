#!/usr/bin/env python3
"""Stress the actual Caspar channel snapshot publication/getter, not a live node.

Requires a C++17 compiler and Boost headers.
This extracts only the monitor handoff; it is not a full-server crash test.
"""
import argparse
import os
import shlex
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--sanitizer', choices=('address', 'thread'), default='address')
    args = parser.parse_args()
    text = (args.source / 'src/core/video_channel.cpp').read_text()
    fields = re.search(r'struct video_channel::impl final\s*\{(.*?)const channel_info channel_info_;', text, re.S).group(1)
    publication = re.search(r'state\["format"\].*?;\s*(.*?)caspar::timer osc_timer;', text, re.S).group(1)
    getter = re.search(r'core::monitor::state video_channel::state\(\) const\s*\{(.*?)\n?\}', text, re.S).group(1)
    # Reject upstream changes rather than accidentally exercising an empty stub.
    assert re.search(r'monitor::state\s+state_', fields)
    assert 'state_' in publication and 'impl_->' in getter
    cpp = r'''
#include "core/monitor/monitor.h"
#include <atomic>
#include <cassert>
#include <iostream>
#include <mutex>
#include <thread>
namespace monitor = caspar::core::monitor;
struct Channel {
 struct Impl {
 FIELDS
 void publish(const monitor::state& state) { PUBLICATION }
 };
 Impl impl;
 Impl* impl_ = &impl;
 monitor::state state() const { GETTER }
};
int main() {
 Channel channel;
 std::atomic<bool> started{false}, done{false};
 std::atomic<unsigned> reads{0};
 std::thread writer([&] {
  while (!started.load()) std::this_thread::yield();
  for (unsigned n=0;n<50000;++n) {
   monitor::state snapshot;
   const auto value=std::string(128, char('a'+n%26));
   for(unsigned k=0;k<32;++k) snapshot["stage"][k]=value;
   channel.impl.publish(snapshot);
  }
  done=true;
 });
 std::thread reader([&] {
  started=true;
  do {
   auto snapshot=channel.state();
   std::string value;
   unsigned count=0;
   for(const auto& item:snapshot) {
    const auto actual=boost::get<std::string>(item.second[0]);
    if(!count++) value=actual;
    assert(value==actual);
   }
   assert(count==0 || count==32);
   ++reads;
  } while(!done.load());
 });
 writer.join(); reader.join();
 assert(reads>0);
 std::cout << "PASS: actual monitor publication/getter survive concurrent snapshots, reads=" << reads << "\n";
}
'''.replace('FIELDS', fields).replace('PUBLICATION', publication).replace('GETTER', getter)
    with tempfile.TemporaryDirectory(prefix='caspar-monitor-snapshot.') as temporary:
        work = Path(temporary)
        source = work / 'test.cpp'
        binary = work / 'test'
        source.write_text(cpp)
        subprocess.run(shlex.split(os.environ.get('CXX', 'c++')) + ['-std=c++17', '-O1', '-g', '-pthread',
                        '-fsanitize='+args.sanitizer, '-fno-omit-frame-pointer',
                        '-I'+str(args.source / 'src'), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], cwd=work, check=True, timeout=60)


if __name__ == '__main__':
    main()
