// Usage: node tools/tests/html_load_error.mjs src/modules/html/producer/html_producer.cpp
// Requires Node.js and a C++17 compiler (CXX defaults to c++).
// Compile the actual Caspar handler with small CEF/state boundary stubs.
// Runtime qualification must additionally exercise the final CEF image.
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

const source = readFileSync(process.argv[2], 'utf8');
const handler = source.slice(source.indexOf('    void OnLoadError('), source.indexOf('    void OnLoadEnd('));
if (!handler.startsWith('    void OnLoadError(')) throw new Error('Caspar load-error handler missing');
const work = mkdtempSync(join(tmpdir(), 'caspar-html-error-policy-'));
try {
  writeFileSync(join(work, 'test.cpp'), `
#include <cassert>
#include <map>
#include <memory>
#include <mutex>
#include <queue>
#include <sstream>
#include <string>
struct CefBrowser {};
struct CefFrame { bool main; bool IsMain() const { return main; } };
struct CefString { std::string ToString() const { return "failed"; } };
template<class T> using CefRefPtr=std::shared_ptr<T>;
enum ErrorCode { ERR_ABORTED=-3, ERR_FAILED=-2 };
#define CASPAR_LOG(level) log
int presentation_frame() { return 0; }
struct Handler {
 bool not_found_=false;
 std::mutex frames_mutex_,state_mutex_;
 std::queue<int> frames_;
 std::map<std::string,std::string> state_{{"file/path","renderer"}};
 std::ostringstream log;
 ${handler.replace(' override', '')}
};
int main() {
 for(bool main: {false,true}) {
  Handler h;
  h.OnLoadError({}, std::make_shared<CefFrame>(CefFrame{main}), ERR_ABORTED, {}, {});
  assert(!h.not_found_ && h.frames_.empty() && h.state_.at("file/path")=="renderer");
 }
 Handler child;
 child.OnLoadError({},std::make_shared<CefFrame>(CefFrame{false}),ERR_FAILED,{},{});
 assert(!child.not_found_ && child.frames_.empty() && child.state_.at("file/path")=="renderer");
 assert(!child.log.str().empty());
 Handler parent;
 parent.OnLoadError({},std::make_shared<CefFrame>(CefFrame{true}),ERR_FAILED,{},{});
 assert(parent.not_found_ && parent.frames_.size()==1 && parent.state_.empty());
}
`);
  execFileSync(process.env.CXX || 'c++', ['-std=c++17', '-o', join(work, 'test'), join(work, 'test.cpp')], { stdio: 'inherit' });
  execFileSync(join(work, 'test'), [], { stdio: 'inherit', cwd: work });
  console.log('PASS: real Caspar handler isolates subframes/cancellation and retains parent failures');
} finally {
  rmSync(work, { recursive: true, force: true });
}
