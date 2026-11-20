"""Flow DOM controls running in the caller's existing native browser session."""
import json


PROJECT_LOCATION = r"(location.origin + location.pathname).replace(/\/$/, '')"


SNAPSHOT = r'''(() => {
  const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const label = e => {
    const copy = e.cloneNode(true);
    copy.querySelectorAll('mat-icon,svg,[aria-hidden=true]').forEach(n=>n.remove());
    return copy.textContent.trim().replace(/\s+/g,' ').replace(/^🍌\s*/,'');
  };
  const agent = Array.from(document.querySelectorAll('button.agent-mode-chip, flow-agent-mode-switch button'))
    .some(button => visible(button) && button.getAttribute('aria-pressed') === 'true')
    || Array.from(document.querySelectorAll('flow-agent-panel')).some(visible);
  const pane = Array.from(document.querySelectorAll('flow-prompt-box-settings,flow-settings-view')).find(visible);
  const groupSelector = pane?.tagName === 'FLOW-PROMPT-BOX-SETTINGS' ? 'flow-toggles' : 'mat-button-toggle-group';
  const groups = pane ? Array.from(pane.querySelectorAll(groupSelector)).map(g=>({
    label:g.getAttribute('aria-label'), options:Array.from(g.querySelectorAll('button[role=radio]')).map(b=>({
      value:label(b), selected:b.getAttribute('aria-checked')==='true', disabled:b.disabled
    }))})) : [];
  const slider = pane?.querySelector('input[type=range]');
  return {url:location.href, time_origin:performance.timeOrigin, mode:agent?'agent':'classic', groups,
    models:pane ? Array.from(pane.querySelectorAll('button[aria-haspopup=menu]')).map(b=>({
      value:label(b), selector:b.classList.contains('image-model-picker-button')?'image':
        b.classList.contains('video-model-picker-button')?'video':'model'})) : [],
    duration:slider?{index:Number(slider.value),min:Number(slider.min),max:Number(slider.max),
      step:Number(slider.step),text:pane.querySelector('.duration-slider-value')?.textContent}:null,
    approval:pane?.querySelector('input[type=radio]:checked')?.value ?? null,
    quote:pane?.querySelector('.cost-text,.credit-cost')?.textContent ?? pane?.innerText.match(/[^\n]*(?:kredit|credits)[^\n]*/i)?.[0],
    ingredients:Array.from(document.querySelectorAll('flow-ingredient-bar img')).filter(visible).map(e=>({
      id:e.getAttribute('data-media-id') ?? e.src.match(/\/image\/([a-f0-9-]+)/)?.[1] ?? null,
      src:e.currentSrc || e.src,ready:e.complete && e.naturalWidth>0})),
    references:Array.from(document.querySelectorAll('flow-ingredient-bar flow-ingredient-chip')).map(e=>{
      const types=['image','video','character','audio'];
      const type=types.find(t=>e.querySelector('flow-'+t+'-ingredient-chip'));
      const button=e.querySelector('button'),img=e.querySelector('img');
      if(!type || !button || !visible(button))return null;
      const disabled=button.disabled||button.getAttribute('aria-disabled')==='true'||button.classList.contains('disabled');
      return {kind:type==='audio'?'voice':type,name:label(e),src:img?.currentSrc || img?.src || null,
        id:img?.src.match(/\/(?:image|video)\/([a-f0-9-]+)/)?.[1] ?? null,
        ready:button.getAttribute('aria-busy')!=='true'&&(type==='audio'||!!(img?.complete&&img?.naturalWidth)),disabled};
    }).filter(Boolean),
    frames:Array.from(document.querySelectorAll('.frame-trigger')).filter(visible).map(e=>({text:label(e),
      image:e.querySelector('img')?.currentSrc ?? null})),
    tiles:Array.from(document.querySelectorAll('flow-image-tile,flow-video-tile')).map(e=>({
      kind:e.tagName==='FLOW-IMAGE-TILE'?'image':'video',id:e.querySelector('[data-media-id]')?.getAttribute('data-media-id') ?? null,
      src:e.querySelector('img')?.currentSrc ?? e.querySelector('video')?.currentSrc ?? null,
      ready:!!((e.querySelector('img')?.complete && e.querySelector('img')?.naturalWidth>0) || e.querySelector('video')?.readyState>=2),
      text:e.innerText,href:e.querySelector('a[href]')?.getAttribute('href') ?? null})),
    notices:Array.from(document.querySelectorAll('[role=alert],mat-snack-bar-container')).map(e=>e.innerText)
  };
})()'''


NATIVE_INPUT = f'PROJECT_LOCATION = {PROJECT_LOCATION!r}\n' + r"""import json,time
def flow_click(selector, text=None, timeout=10, project=None):
    deadline = time.monotonic() + timeout
    while True:
        point = js(r'''(() => {
              const project = %s;
              if (project !== null && %s !== project) return false;
              const label = e => {
                const primary = e.querySelector('.item-text > .label');
                if (primary) return primary.textContent.trim().replace(/^🍌\s*/,'');
                const copy = e.cloneNode(true);
                copy.querySelectorAll('mat-icon,svg,[aria-hidden=true]').forEach(n => n.remove());
                return copy.textContent.trim().replace(/\s+/g,' ').replace(/^🍌\s*/,'');
              };
              const nodes = Array.from(document.querySelectorAll(%s)).filter(e =>
                e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' &&
                (%s === null || label(e) === %s));
              if (nodes.length > 1) throw Error('Flow control matches multiple visible elements: ' + %s);
              const e = nodes[0];
              if (!e || e.disabled || e.getAttribute('aria-disabled') === 'true') return null;
              e.scrollIntoView({block:'nearest', inline:'nearest'});
              const r = e.getBoundingClientRect();
              const x = r.x + r.width / 2, y = r.y + r.height / 2;
              return r.width && r.height && e.contains(document.elementFromPoint(x,y)) ? [x,y] : null;
            })()''' % (json.dumps(project), PROJECT_LOCATION, json.dumps(selector),
                        json.dumps(text), json.dumps(text), json.dumps(selector + ' ' + str(text))))
        if point is False:
            return False
        if point is not None:
            click_at_xy(*point)
            return True
        if time.monotonic() >= deadline:
            raise RuntimeError('Flow control is unavailable: ' + selector + ' ' + str(text))
        time.sleep(.1)
"""


class UI:
    def __init__(self, context):
        self.context = context

    def execute(self, code, timeout=60):
        result = self.context.browser_exec(
            NATIVE_INPUT + '\n' + code, timeout_s=timeout)
        if not result.get('success') or result.get('exit_code', 0):
            raise RuntimeError(result.get('error') or result.get('stderr') or result.get('output') or str(result))
        values = [json.loads(line[len('FLOW_VALUE='):])
                  for line in result.get('output', '').splitlines() if line.startswith('FLOW_VALUE=')]
        return values[-1] if values else None

    def read(self, expression):
        return self.execute(f"print('FLOW_VALUE=' + str(js({('JSON.stringify(' + expression + ')')!r})))")

    def click(self, selector, text=None, *, project=None):
        if project is None:
            self.execute(f'flow_click({selector!r}, {text!r})')
            return
        return self.execute(
            f"print('FLOW_VALUE=' + json.dumps(flow_click({selector!r}, {text!r}, project={project!r})))")

    def snapshot(self):
        return self.read(SNAPSHOT)

    def fill(self, selector, text):
        self.execute(f'fill_input({selector!r}, {text!r})')

    def mode(self, mode):
        if mode not in {'classic', 'agent'}:
            raise ValueError('mode must be classic or agent')
        if self.snapshot()['mode'] == mode:
            return
        if self.read("Array.from(document.querySelectorAll('flow-agent-panel')).some(e=>e.getClientRects().length)"):
            self.click('flow-agent-panel button.header-action[aria-label="Tutup"],'
                       'flow-agent-panel button.header-action[aria-label="Close"]')
            self.wait("!Array.from(document.querySelectorAll('flow-agent-panel')).some(e=>e.getClientRects().length)")
        self.click('button.agent-mode-chip, flow-agent-mode-switch button')
        self.wait(f'({SNAPSHOT}).mode === {json.dumps(mode)}')

    def settings(self, mode):
        if mode == 'classic':
            if not self.read("!!document.querySelector('flow-prompt-box-settings')?.getClientRects().length"):
                self.click('button.settings-trigger-button')
            self.wait("!!document.querySelector('flow-prompt-box-settings')?.getClientRects().length")
        else:
            if not self.read("!!document.querySelector('flow-settings-view')?.getClientRects().length"):
                self.click('button.agent-action-button[aria-label="Setelan"],'
                           'button.agent-action-button[aria-label="Settings"]')
            self.wait("!!document.querySelector('flow-settings-view')?.getClientRects().length")

    def close_settings(self, mode):
        pane = 'flow-prompt-box-settings' if mode == 'classic' else 'flow-settings-view'
        if not self.read(f"!!document.querySelector('{pane}')?.getClientRects().length"):
            return
        if self.read("Array.from(document.querySelectorAll('[role=menuitem]')).some(e=>e.getClientRects().length)"):
            self.execute("press_key('Escape')")
        self.click('button.settings-trigger-button' if mode == 'classic' else 'button.settings-save-button')

    def choose(self, group, value):
        state = self.snapshot()
        options = state['groups'][group]['options']
        option = next((item for item in options if item['value'] == value), None)
        if option is None or option['disabled']:
            raise ValueError(f'Unavailable Flow value {value!r}. Available options: {options}')
        if option['selected']:
            return
        # Group order comes from the current settings pane, including conditional controls.
        selector = self.read("(() => {const p=Array.from(document.querySelectorAll('flow-prompt-box-settings,flow-settings-view')).find(e=>e.getClientRects().length);"
            "const s=p.tagName==='FLOW-PROMPT-BOX-SETTINGS'?'flow-toggles':'mat-button-toggle-group';"
            f"const g=p.querySelectorAll(s)[{group}];"
            "g.setAttribute('data-hermes-flow-group','selected');return '[data-hermes-flow-group=selected] button[role=radio]';})()")
        try:
            self.click(selector, value)
            self.wait(f"({SNAPSHOT}).groups[{group}].options.some(o=>o.value==={json.dumps(value)} && o.selected)")
        finally:
            self.read("(() => {document.querySelectorAll('[data-hermes-flow-group]').forEach(e=>e.removeAttribute('data-hermes-flow-group'));return true;})()")

    def model(self, mode, kind, value=None):
        category = 'model' if mode == 'classic' else kind
        self.wait(f"({SNAPSHOT}).models.some(item=>item.selector==={json.dumps(category)}&&item.value)")
        selected = next(item['value'] for item in self.snapshot()['models']
                        if item['selector'] == category)
        selector = ('flow-prompt-box-settings button[aria-haspopup=menu]' if mode == 'classic'
                    else f'flow-settings-view button.{kind}-model-picker-button')
        self.click(selector)
        self.wait("Array.from(document.querySelectorAll('[role=menuitem]')).some(e=>e.getClientRects().length)")
        options = self.read("Array.from(document.querySelectorAll('[role=menuitem]')).map(e=>({"
            "value:(e.querySelector('.item-text > .label')?.textContent ?? e.innerText).trim().replace(/^🍌\\s*/,''),"
            "disabled:e.getAttribute('aria-disabled')==='true'}))")
        if value is None:
            self.click('[role=menuitem]', selected)
        elif any(item['value'] == value and not item['disabled'] for item in options):
            self.click('[role=menuitem]', value)
        else:
            self.execute("press_key('Escape')")
            raise ValueError(f'Unavailable Flow model {value!r}. Available options: {options}')
        return options

    def duration(self, seconds):
        state = self.snapshot()
        slider = state['duration']
        if not slider:
            raise ValueError('The selected Flow model does not expose a duration slider')
        # Drive the native slider with keyboard events and read the displayed seconds.
        self.click('flow-prompt-box-settings input[type=range]')
        self.execute("press_key('Home')")
        for _ in range(int((slider['max'] - slider['min']) / slider['step']) + 1):
            current = self.snapshot()['duration']
            displayed = current['text'].split()[0]
            if displayed == str(seconds):
                return
            if current['index'] >= current['max']:
                break
            self.execute("press_key('ArrowRight')")
        raise ValueError('Requested seconds are unavailable on this Flow duration control')

    def wait(self, expression, timeout=20):
        code = f'''import time
deadline = time.monotonic() + {timeout!r}
while True:
    value = js({expression!r})
    if value:
        break
    if time.monotonic() >= deadline:
        raise RuntimeError({'Flow state did not become ready: ' + expression[:500]!r})
    wait(.2)
'''
        self.execute(code, timeout + 10)
