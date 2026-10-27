"""Plugin-owned browser helper snapshot. See vendor/PROVENANCE.md and LICENSE.

Executed in a fresh worker namespace with cdp, _send and AGENT_WORKSPACE
injected by worker.helper_namespace. Never imports the installed harness.
"""
import base64, json, math, os, re, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse

INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")


DEFAULT_IPC_RESPONSE_TIMEOUT_SECONDS = 5.0


SCREENSHOT_IPC_RESPONSE_TIMEOUT_SECONDS = 60.0


class _IPCResponseTimeout(TimeoutError):
    pass


def drain_events():  return _send({"meta": "drain_events"})["events"]


def _js_snippet(expression, limit=160):
    snippet = expression.strip().replace("\n", "\\n")
    return snippet[:limit - 3] + "..." if len(snippet) > limit else snippet


def _js_exception_description(result, details):
    desc = result.get("description")
    exc = details.get("exception") if details else None
    if not desc and isinstance(exc, dict):
        desc = exc.get("description")
        if desc is None and "value" in exc:
            desc = str(exc["value"])
        if desc is None:
            desc = exc.get("className")
    if not desc and details:
        desc = details.get("text")
    return desc or "JavaScript evaluation failed"


def _decode_unserializable_js_value(value):
    if value == "NaN":
        return math.nan
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    if value == "-0":
        return -0.0
    if value.endswith("n"):
        return int(value[:-1])
    return value


def _runtime_value(response, expression):
    result = response.get("result", {})
    details = response.get("exceptionDetails")
    if details or result.get("subtype") == "error":
        desc = _js_exception_description(result, details)
        if details:
            line = details.get("lineNumber")
            col = details.get("columnNumber")
            loc = f" at line {line}, column {col}" if line is not None and col is not None else ""
        else:
            loc = ""
        raise RuntimeError(f"JavaScript evaluation failed{loc}: {desc}; expression: {_js_snippet(expression)}")
    if "value" in result:
        return result["value"]
    if "unserializableValue" in result:
        return _decode_unserializable_js_value(result["unserializableValue"])
    return None


def _runtime_evaluate(expression, session_id=None, await_promise=False):
    try:
        r = cdp("Runtime.evaluate", session_id=session_id, expression=expression, returnByValue=True, awaitPromise=await_promise)
    except TimeoutError as e:
        raise RuntimeError(f"Runtime.evaluate timed out; expression: {_js_snippet(expression)}") from e
    return _runtime_value(r, expression)


def _wrap_js_function(expression):
    return f"(function(){{{expression}}})()"


def _is_illegal_return_error(exc):
    return "Illegal return statement" in str(exc)


def goto_url(url):
    r = cdp("Page.navigate", url=url)
    if os.environ.get("BH_DOMAIN_SKILLS") != "1" or AGENT_WORKSPACE is None:
        return r
    d = (AGENT_WORKSPACE / "domain-skills" / (urlparse(url).hostname or "").removeprefix("www.").split(".")[0])
    return {**r, "domain_skills": sorted(p.name for p in d.rglob("*.md"))[:10]} if d.is_dir() else r


def page_info():
    """{url, title, w, h, sx, sy, pw, ph} — viewport + scroll + page size.

    If a native dialog (alert/confirm/prompt/beforeunload) is open, returns
    {dialog: {type, message, ...}} instead — the page's JS thread is frozen
    until the dialog is handled (see interaction-skills/dialogs.md)."""
    dialog = _send({"meta": "pending_dialog"}).get("dialog")
    if dialog:
        return {"dialog": dialog}
    expression = "JSON.stringify({url:location.href,title:document.title,w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})"
    return json.loads(_runtime_evaluate(expression))


_debug_click_counter = 0


def click_at_xy(x, y, button="left", clicks=1):
    if os.environ.get("BH_DEBUG_CLICKS"):
        global _debug_click_counter
        try:
            from PIL import Image, ImageDraw
            dpr = js("window.devicePixelRatio") or 1
            path = capture_screenshot(str(AGENT_WORKSPACE / f"debug_click_{_debug_click_counter}.png"))
            img = Image.open(path)
            draw = ImageDraw.Draw(img)
            px, py = int(x * dpr), int(y * dpr)
            r = int(15 * dpr)
            draw.ellipse([px - r, py - r, px + r, py + r], outline="red", width=int(3 * dpr))
            draw.line([px - r - int(5 * dpr), py, px + r + int(5 * dpr), py], fill="red", width=int(2 * dpr))
            draw.line([px, py - r - int(5 * dpr), px, py + r + int(5 * dpr)], fill="red", width=int(2 * dpr))
            img.save(path)
            print(f"[debug_click] saved {path} (x={x}, y={y}, dpr={dpr})")
        except Exception as e:
            print(f"[debug_click] overlay failed: {e}")
        _debug_click_counter += 1
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)


def type_text(text):
    cdp("Input.insertText", text=text)


_SELECT_ALL_MODIFIER = None


def _select_all_modifier():
    """Select-all modifier by the browser's OS (not this process's): 4=Meta on macOS, else 2=Ctrl."""
    global _SELECT_ALL_MODIFIER
    if _SELECT_ALL_MODIFIER is None:
        ua = cdp("Browser.getVersion").get("userAgent", "")
        _SELECT_ALL_MODIFIER = 4 if "Mac OS X" in ua or "Macintosh" in ua else 2
    return _SELECT_ALL_MODIFIER


def fill_input(selector, text, clear_first=True, timeout=0.0):
    """Fill a framework-managed input (React controlled, Vue v-model, Ember tracked).

    type_text() uses Input.insertText which bypasses framework event listeners and leaves
    submit buttons disabled. This helper focuses the element, clears it, types via real
    key events, then fires synthetic input+change events so the framework sees the update.

    Raises RuntimeError if the element is not found. Pass timeout>0 to wait for
    late-rendered elements (e.g. after a route change) before typing.
    """
    if timeout > 0:
        if not wait_for_element(selector, timeout=timeout):
            raise RuntimeError(f"fill_input: element not found: {selector!r}")
    focused = js(
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return false;e.focus();return true;}})()"
    )
    if not focused:
        raise RuntimeError(f"fill_input: element not found: {selector!r}")
    if clear_first:
        # Dispatch select-all directly — NOT via press_key, which always emits a
        # `char` event for single-char keys. With Ctrl/Cmd held, that `char`
        # makes Chrome treat the input as a printable "a" instead of firing the
        # select-all shortcut, leaving the field uncleared.
        mods = _select_all_modifier()
        select_all = {"key": "a", "code": "KeyA", "modifiers": mods,
                      "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65,
                      "commands": ["SelectAll"]}
        cdp("Input.dispatchKeyEvent", type="rawKeyDown", **select_all)
        cdp("Input.dispatchKeyEvent", type="keyUp",
            **{k: v for k, v in select_all.items() if k != "commands"})
        press_key("Backspace")
    for ch in text:
        press_key(ch)
    js(
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return;"
        f"e.dispatchEvent(new Event('input',{{bubbles:true}}));"
        f"e.dispatchEvent(new Event('change',{{bubbles:true}}));}})();"
    )


_KEYS = {  # key → (windowsVirtualKeyCode, code, text)
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"), "Backspace": (8, "Backspace", ""),
    "Escape": (27, "Escape", ""), "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
    "Home": (36, "Home", ""), "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""), "PageDown": (34, "PageDown", ""),
}


_PUNCTUATION_KEYS = {
    "`": ("Backquote", 192), "-": ("Minus", 189), "=": ("Equal", 187),
    "[": ("BracketLeft", 219), "]": ("BracketRight", 221), "\\": ("Backslash", 220),
    ";": ("Semicolon", 186), "'": ("Quote", 222), ",": ("Comma", 188),
    ".": ("Period", 190), "/": ("Slash", 191),
}


_SHIFTED_CHARS = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=",
    "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
}


def _printable_key(char):
    """(code, virtual key, needs_shift) for one printable ASCII char on a US layout.

    None when the character has no US physical key — accented letters, CJK,
    emoji. Those still insert from the char event's text, and inventing a
    keyboard key for them would just be a different wrong answer.
    """
    unshifted = _SHIFTED_CHARS.get(char, char)
    needs_shift = char in _SHIFTED_CHARS or char.isupper()
    if unshifted.isascii() and "a" <= unshifted.lower() <= "z":
        return f"Key{unshifted.upper()}", ord(unshifted.upper()), needs_shift
    if unshifted.isdigit() and unshifted.isascii():
        return f"Digit{unshifted}", ord(unshifted), needs_shift
    if unshifted in _PUNCTUATION_KEYS:
        code, vk = _PUNCTUATION_KEYS[unshifted]
        return code, vk, needs_shift
    return None


def press_key(key, modifiers=0):
    """Modifiers bitfield: 1=Alt, 2=Ctrl, 4=Meta(Cmd), 8=Shift.

    Named keys (Enter, Tab, Arrow*, Backspace, ...) and printable characters alike
    carry the physical `code` and virtual key code a real US keyboard sends, so
    listeners reading e.key, e.code and e.keyCode all agree. A character that
    needs Shift on that layout (uppercase, !@#$...) sets the Shift modifier too,
    unless the caller is already composing a shortcut with Alt/Ctrl/Meta — there,
    the caller's intent wins over the physical truth.
    """
    if key in _KEYS:
        vk, code, text = _KEYS[key]
    elif len(key) == 1:
        text = key
        resolved = _printable_key(key)
        if resolved:
            code, vk, needs_shift = resolved
            if needs_shift and not modifiers & (1 | 2 | 4):
                modifiers |= 8
        else:
            code, vk = "", 0
    else:
        vk, code, text = 0, key, ""
    base = {"key": key, "code": code, "modifiers": modifiers, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    shortcut_modifiers = modifiers & (1 | 2 | 4)  # Alt/Ctrl/Meta turn single keys into shortcuts.
    printable_char = len(key) == 1 and bool(text) and not shortcut_modifiers
    cdp("Input.dispatchKeyEvent", type="keyDown", **base, **({} if printable_char or not text else {"text": text}))
    if printable_char:
        cdp("Input.dispatchKeyEvent", type="char", text=text, **{k: v for k, v in base.items() if k != "text"})
    cdp("Input.dispatchKeyEvent", type="keyUp", **base)


def scroll(x, y, dy=-300, dx=0):
    cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)


def capture_screenshot(path=None, full=False, max_dim=None):
    """Save a PNG of the current viewport. Set max_dim=1800 on a 2× display to
    keep the file under the 2000px-per-side limit some image-aware LLMs enforce."""
    path = path or str(AGENT_WORKSPACE / "shot.png")
    try:
        r = cdp(
            "Page.captureScreenshot",
            _response_timeout=SCREENSHOT_IPC_RESPONSE_TIMEOUT_SECONDS,
            format="png",
            captureBeyondViewport=full,
        )
    except _IPCResponseTimeout as e:
        raise RuntimeError(
            f"Page.captureScreenshot timed out after {SCREENSHOT_IPC_RESPONSE_TIMEOUT_SECONDS:g}s"
        ) from e
    open(path, "wb").write(base64.b64decode(r["data"]))
    if max_dim:
        from PIL import Image
        img = Image.open(path)
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
            img.save(path)
    return path


def _is_agent_startup_placeholder(title, url):
    url = str(url or "")
    return str(title or "").startswith("Starting agent ") and (
        url in ("", "about:blank") or url.startswith("about:blank#")
    )


def list_tabs(include_chrome=True):
    out = []
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] != "page": continue
        url = t.get("url", "")
        if _is_agent_startup_placeholder(t.get("title", ""), url): continue
        if not include_chrome and url.startswith(INTERNAL): continue
        out.append({
            "targetId": t["targetId"],
            "target_id": t["targetId"],
            "title": t.get("title", ""),
            "url": url,
        })
    return out


def current_tab():
    r = _send({"meta": "current_tab"})
    return {
        "targetId": r["targetId"],
        "target_id": r["targetId"],
        "url": r["url"],
        "title": r["title"],
    }


def _mark_tab():
    """Prepend horse emoji to tab title so the user can see which tab the agent controls."""
    if os.environ.get("BH_TAB_MARKER", "").strip().lower() in {"0", "false", "no", "off"}:
        return
    try: cdp("Runtime.evaluate", expression="if(!document.title.startsWith('\U0001F434'))document.title='\U0001F434 '+document.title")
    except Exception: pass


def _target_id(target):
    """Accept a raw target id or a tab dict returned by the helpers."""
    return (target.get("targetId") or target.get("target_id")) if isinstance(target, dict) else target


def activate_tab(target):
    """Make a target the visible Chrome tab.

    This is intentionally separate from switch_tab(): attaching the agent to a
    target does not require taking over the user's visible Chrome tab.
    """
    target_id = _target_id(target)
    cdp("Target.activateTarget", targetId=target_id)
    return target_id


def close_tab(target=None):
    """Close a tab. If `target` is omitted, closes the currently attached tab.
    Accepts a raw targetId string or a dict from list_tabs()/current_tab()."""
    target_id = _target_id(target)
    if target_id is None:
        target_id = current_tab()["targetId"]
    cdp("Target.closeTarget", targetId=target_id)


def iframe_target(url_substr):
    """First iframe target whose URL contains `url_substr`. Use with js(..., target_id=...)."""
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] == "iframe" and url_substr in t.get("url", ""):
            return t["targetId"]
    return None


def wait(seconds=1.0):
    time.sleep(seconds)


def wait_for_load(timeout=15.0):
    """Poll document.readyState == 'complete' or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js("document.readyState") == "complete": return True
        time.sleep(0.3)
    return False


def wait_for_element(selector, timeout=10.0, visible=False):
    """Poll until querySelector(selector) exists in the DOM, or timeout.

    wait_for_load() misses SPAs — the document is 'complete' before the framework renders.
    Use this after actions that trigger async rendering (route changes, data fetches).
    Set visible=True to also require the element to be non-hidden and in-layout.
    Returns True if found, False on timeout.
    """
    if visible:
        # checkVisibility walks the ancestor chain and respects display:none /
        # visibility:hidden / opacity:0 on parents, which a getComputedStyle
        # check on the element alone misses (it returns the descendant's own
        # style, not the inherited "is this rendered" state). Falls back to
        # the per-element CSS check on older Chrome that lacks checkVisibility.
        check = (
            f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
            f"if(!e)return false;"
            f"if(typeof e.checkVisibility==='function')"
            f"return e.checkVisibility({{checkOpacity:true,checkVisibilityCSS:true}});"
            f"const s=getComputedStyle(e);"
            f"return s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'}})()"
        )
    else:
        check = f"!!document.querySelector({json.dumps(selector)})"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js(check): return True
        time.sleep(0.3)
    return False


def wait_for_network_idle(timeout=10.0, idle_ms=500):
    """Wait until all in-flight requests finish and no Network.* events arrive for idle_ms ms.

    Useful after form submits, SPA route transitions, and any action that triggers
    XHR/fetch without a visible DOM change. Builds on drain_events() — no daemon changes.
    Returns True if idle window reached, False on timeout.

    Events are filtered to the active session — a previously-attached background
    tab (e.g. a polling/SSE page the agent switched away from) keeps emitting
    Network events into the daemon's global event buffer; without this filter
    they would poison the idle check on the current tab.
    """
    deadline = time.time() + timeout
    last_activity = time.time()
    inflight = set()
    active_session = _send({"meta": "session"}).get("session_id")
    while time.time() < deadline:
        for e in drain_events():
            if e.get("session_id") != active_session:
                continue
            method = e.get("method", "")
            params = e.get("params", {})
            if method == "Network.requestWillBeSent":
                inflight.add(params.get("requestId"))
                last_activity = time.time()
            elif method in ("Network.loadingFinished", "Network.loadingFailed"):
                inflight.discard(params.get("requestId"))
                last_activity = time.time()
            elif method.startswith("Network."):
                last_activity = time.time()
        if not inflight and (time.time() - last_activity) * 1000 >= idle_ms:
            return True
        time.sleep(0.1)
    return False


def js(expression, target_id=None):
    """Run JS in the attached tab (default) or inside an iframe target (via iframe_target()).

    Expressions are evaluated as-is first. If Chrome reports an illegal top-level
    `return`, the snippet is retried inside a function wrapper, so both
    `document.title` and `const x = 1; return x` work without mis-wrapping nested
    functions that contain their own returns.
    """
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"] if target_id else None
    try:
        result = _js_evaluate(expression, sid)
    except BaseException:
        # Keep the evaluation error; a detach failure here must not replace it.
        if sid:
            try:
                _detach_iframe_session(sid)
            except BaseException:
                pass
        raise
    if sid:
        _detach_iframe_session(sid)
    return result


def _js_evaluate(expression, sid):
    try:
        return _runtime_evaluate(expression, session_id=sid, await_promise=True)
    except RuntimeError as e:
        if _is_illegal_return_error(e):
            return _runtime_evaluate(_wrap_js_function(expression), session_id=sid, await_promise=True)
        raise


def _detach_iframe_session(sid):
    """Release the session js(target_id=...) attached so polling loops do not
    accumulate one live session (and one event stream) per call. A session that
    Chrome already dropped (iframe navigated or closed) is not a leak."""
    try:
        cdp("Target.detachFromTarget", sessionId=sid)
    except Exception as e:
        message = str(e).lower()
        if "no session with given id" in message or "session with given id not found" in message:
            return
        raise


_KC = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, " ": 32, "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40}


def dispatch_key(selector, key="Enter", event="keypress"):
    """Dispatch a DOM KeyboardEvent on the matched element.

    Use this when a site reacts to synthetic DOM key events on an element more reliably
    than to raw CDP input events.
    """
    kc = _KC.get(key, ord(key) if len(key) == 1 else 0)
    js(
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(e){{e.focus();e.dispatchEvent(new KeyboardEvent({json.dumps(event)},{{key:{json.dumps(key)},code:{json.dumps(key)},keyCode:{kc},which:{kc},bubbles:true}}));}}}})()"
    )


def upload_file(selector, path):
    """Set files on a file input via CDP DOM.setFileInputFiles. `path` is an absolute filepath (use tempfile.mkstemp if needed)."""
    doc = cdp("DOM.getDocument", depth=-1)
    nid = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)["nodeId"]
    if not nid: raise RuntimeError(f"no element for {selector}")
    cdp("DOM.setFileInputFiles", files=[path] if isinstance(path, str) else list(path), nodeId=nid)


def http_get(url, headers=None, timeout=20.0):
    """Pure HTTP — no browser. Use for static pages / APIs. Wrap in ThreadPoolExecutor for bulk.

    When BROWSER_USE_API_KEY is set, routes through the fetch-use proxy (handles bot
    detection, residential proxies, retries). Falls back to local urllib otherwise."""
    if os.environ.get("BROWSER_USE_API_KEY"):
        try:
            from fetch_use import fetch_sync
            return fetch_sync(url, headers=headers, timeout_ms=int(timeout * 1000)).text
        except ImportError:
            pass
    import gzip
    h = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
    if headers: h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip": data = gzip.decompress(data)
        return data.decode()


_TEXT_LIMIT = 500

_URL_SECRETS = re.compile(
    r"([?&#](?:code|access_token|id_token|refresh_token|token|assertion"
    r"|client_secret|client_info|session_state|api_?key|sig|signature"
    r"|auth|authorization|password|secret)=)[^&#]+",
    re.IGNORECASE,
)

def _scrub_url(url):
    return _URL_SECRETS.sub(r"\1REDACTED", str(url))

_CTX_JS = (
    "(()=>{const o={url:location.href,title:document.title,"
    "w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,dpr:devicePixelRatio};"
    "const e=document.activeElement;"
    "if(e&&e!==document.body&&e!==document.documentElement){"
    "const r=e.getBoundingClientRect();"
    "if(r.width||r.height)o.box={x:r.x,y:r.y,w:r.width,h:r.height};"
    "o.input=String(e.type||e.tagName||'').toLowerCase();}"
    "return o})()"
)

def _env_override():
    raw = os.environ.get("BH_RECORD")
    if raw is None:
        return None
    return raw.strip().lower() not in ("0", "false", "no", "off")

def _marker():
    return _recordings_root() / f".active-{os.environ.get('BU_NAME', 'default')}"

def start_recording(name=None, title=None):
    """Record the session: one screenshot + trace line per action, until
    stop_recording(). Survives across CLI invocations. Returns the recording
    directory. `title` is used later as the video title.
    See interaction-skills/make-video.md to turn the recording into a video."""
    if _env_override() is False:
        raise RuntimeError("recording disabled by BH_RECORD=0")
    name = name or time.strftime("rec-%Y%m%d-%H%M%S")
    d = _recordings_root() / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {"name": name, "title": title, "started": round(time.time(), 3)}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    _marker().write_text(str(d), encoding="utf-8")
    _capture(d, "start_recording")
    print(f"recording to {d}")
    return str(d)

def stop_recording():
    """Stop the active recording. Returns its directory, or None if idle."""
    d = recording_dir()
    if d is None:
        print("no active recording")
        return None
    _capture(Path(d), "stop_recording")
    _marker().unlink(missing_ok=True)
    frames = sum(1 for _ in Path(d).glob("*.jpg"))
    print(f"recording saved: {d} ({frames} frames)")
    if not frames:
        print(f"warning: no frames captured — see frame_error in {Path(d) / 'events.jsonl'}")
    return d

def recording_dir():
    """Directory of the active recording, or None."""
    m = _marker()
    if not m.exists():
        return None
    d = m.read_text(encoding="utf-8").strip()
    return d if Path(d).is_dir() else None

def _capture(d, helper, args=(), kwargs=None, duration=None):

    event = {"ts": round(time.time(), 3), "helper": helper}
    if duration is not None:
        event["duration"] = duration
    try:
        event.update(js(_CTX_JS) or {})
    except Exception:
        pass
    event.update(_details(helper, args, kwargs or {}, event))
    for k in ("url", "to"):
        if k in event:
            event[k] = _scrub_url(event[k])
    try:
        # Same budget capture_screenshot() uses: a cloud screenshot routinely
        # exceeds the 5s default IPC timeout, and every frame here would time
        # out and be swallowed below, leaving a recording with no frames.
        shot = cdp(
            "Page.captureScreenshot",
            _response_timeout=SCREENSHOT_IPC_RESPONSE_TIMEOUT_SECONDS,
            format="jpeg",
            quality=80,
        )
        number = sum(1 for _ in d.glob("*.jpg")) + 1
        data = base64.b64decode(shot["data"])
        while True:
            frame = f"{number:04d}.jpg"
            try:
                with (d / frame).open("xb") as output:
                    output.write(data)
                break
            except FileExistsError:
                number += 1
        event["frame"] = frame
    except Exception as e:
        # A dropped frame must not break the run, but it must not vanish
        # either — without this the only symptom is a recording that ends up
        # with fewer frames than actions, and no way to tell why.
        # `str(e) or ...` because an exception raised bare (no args) stringifies
        # to "", which would record a useless "SomeError: " and defeat the point.
        event["frame_error"] = f"{type(e).__name__}: {str(e) or 'no detail'}"[:200]
    # Page-controlled strings (document.title etc.) can carry lone surrogates
    # in through CDP's \uDXXX escapes; they can't encode as UTF-8, and one
    # would kill the whole trace. Replace with U+FFFD — same medicine run.py
    # already gives stdout (#124).
    with (d / "events.jsonl").open("a", encoding="utf-8", errors="replace") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def _details(helper, args, kwargs, ctx):
    def arg(i, name, default=None):
        return args[i] if len(args) > i else kwargs.get(name, default)

    d = {}
    if helper == "click_at_xy":
        d["x"], d["y"] = arg(0, "x"), arg(1, "y")
    elif helper == "scroll":
        d["x"], d["y"] = arg(0, "x"), arg(1, "y")
        d["dy"], d["dx"] = arg(2, "dy", -300), arg(3, "dx", 0)
    elif helper in ("goto_url", "new_tab"):
        d["to"] = arg(0, "url")
    elif helper == "type_text":
        d["text"] = _mask(arg(0, "text", ""), ctx)
    elif helper == "fill_input":
        d["selector"] = arg(0, "selector")
        d["text"] = _mask(arg(1, "text", ""), ctx)
    elif helper == "press_key":
        d["key"] = arg(0, "key")
    elif helper == "dispatch_key":
        d["selector"], d["key"] = arg(0, "selector"), arg(1, "key", "Enter")
    elif helper == "wait_for_element":
        d["selector"] = arg(0, "selector")
    return {k: v for k, v in d.items() if v is not None}

def _mask(text, ctx):
    text = str(text)
    if ctx.get("input") == "password":
        return "•" * len(text)
    return text[:_TEXT_LIMIT]

def _recordings_root():
    return AGENT_WORKSPACE / "recordings"
