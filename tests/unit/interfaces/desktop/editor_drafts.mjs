// No browser dependencies: exercise the actual modules against narrowly scoped
// DOM doubles. The full browser smoke covers native editing/rendering behavior.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';

const [assets, scenario] = process.argv.slice(2);
class Classes {
  values = new Set();
  toggle(name, enabled) { if (enabled) this.values.add(name); else this.values.delete(name); }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  contains(name) { return this.values.has(name); }
}
class Element {
  constructor(tagName = 'DIV', ...children) {
    this.nodeType = 1;
    this.tagName = tagName;
    this.dataset = {};
    this.childNodes = children;
    this.classList = new Classes();
    this.controls = {};
    this.attributes = {};
    this.textContent = '';
    this.value = '';
    children.forEach((node, index) => {node.nextSibling = children[index + 1] || null;});
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  getAttribute(key) { return this.attributes[key] ?? this[key] ?? null; }
  replaceChildren(...children) { this.childNodes = children; }
  append(...children) { this.childNodes.push(...children); }
  focus() {}
  closest(selector) { return selector === '.translation-block' ? this.blockElement : null; }
  querySelector(selector) {
    if (selector === '.translated-editor.is-dirty') return this.editors?.find((editor) => editor.classList.contains('is-dirty'));
    return this.controls[selector] || null;
  }
  querySelectorAll(selector) {
    if (selector === '.translated-editor' || selector === '.paragraph-fragment-editor') return this.editors || [];
    return [];
  }
  getBoundingClientRect() { return {top: 0}; }
}
class HTMLInputElement extends Element {}
class HTMLSelectElement extends Element {}
const text = (value) => ({nodeType: 3, textContent: value});
const elements = [];
const buttons = [];
const state = {
  jobId: 'test-run', review: {cost: {total: 1}}, blockIndex: new Map(),
  reviewDrafts: new Map(), reviewMutationPending: false, uncertaintyIndex: new Map(),
};
const translationContent = new Element();
translationContent.querySelectorAll = (selector) => {
  if (selector === '.translated-editor') return elements;
  if (selector.includes("data-action='save-")) return buttons;
  if (selector === '.translation-block') return elements.map((element) => element.blockElement);
  return [];
};
translationContent.contains = () => true;
const contextSource = readFileSync(join(assets, 'context.js'), 'utf8');
const contextExports = Object.fromEntries([...contextSource.matchAll(/export const (\w+)/g)]
  .map((match) => [match[1], new Element()]));
Object.assign(contextExports, {state, translationContent, translationScroll: new Element()});
let request = async () => { throw new Error('Unexpected request'); };
const rendered = [];
const byId = new Map();
const sandbox = vm.createContext({
  console, Map, Set, Element, HTMLInputElement, HTMLSelectElement,
  CustomEvent: class { constructor(type) { this.type = type; } },
  document: {dispatchEvent() {}, activeElement: null, createTextNode: text,
    getElementById(id) {if (!byId.has(id)) byId.set(id, new Element()); return byId.get(id);}}, window: {getSelection: () => null},
  requestAnimationFrame() {},
});
const modules = new Map();
function synthetic(name, exports) {
  const module = new vm.SyntheticModule(Object.keys(exports), function() {
    for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
  }, {context: sandbox, identifier: name});
  modules.set(name, module);
}
synthetic('context.js', contextExports);
synthetic('api.js', {apiRequest: (...args) => request(...args)});
synthetic('review.js', {renderReview: (drafts, options) => {
  state.reviewDrafts = new Map(drafts);
  rendered.push({drafts, options});
}});
if (!['merged_page_navigation', 'short_final_page'].includes(scenario)) {
  synthetic('pages.js', {activateSourcePageNumber() {}, setReviewZoom() {}});
}
synthetic('viewport.js', {resizeSourceImage() {}, sourceImageLoading() {}});
async function load(name) {
  if (!modules.has(name)) {
    const module = new vm.SourceTextModule(readFileSync(join(assets, name), 'utf8'), {
      context: sandbox, identifier: name,
    });
    modules.set(name, module);
    await module.link((specifier) => load(specifier.replace('./', '')));
  }
  return modules.get(name);
}
async function importModule(name) {
  const module = await load(name);
  if (module.status !== 'evaluated') await module.evaluate();
  return module.namespace;
}
function makeEditor(id, value = 'Original text') {
  const block = {block_id: id, type: 'body', effective_text: value, base_revision: 0};
  const editor = new Element('DIV', text(value));
  editor.dataset.blockId = id;
  const blockElement = new Element();
  blockElement.dataset = {blockId: id, pageNumber: '1'};
  blockElement.editors = [editor];
  editor.blockElement = blockElement;
  state.blockIndex.set(id, {block, page: {original_page_number: 1}});
  elements.push(editor);
  const type = new HTMLSelectElement();
  type.value = 'body';
  const owner = new HTMLSelectElement();
  const anchor = new HTMLInputElement();
  anchor.value = '0';
  Object.assign(blockElement.controls, {
    '.section-type-select': type, '.footnote-owner-select': owner,
    '.footnote-anchor-input': anchor, '.block-message': new Element(),
  });
  for (const control of Object.values(blockElement.controls)) control.blockElement = blockElement;
  const button = new Element();
  buttons.push(button);
  return {block, editor, blockElement, type, owner, anchor, button,
    message: blockElement.controls['.block-message']};
}
function changeText(editor, value) { editor.childNodes = [text(value)]; }
function deferred() {
  let resolve;
  const promise = new Promise((done) => {resolve = done;});
  return {promise, resolve};
}
const drafts = await importModule('drafts.js');
if (scenario === 'native_line_breaks') {
  const marker = new Element('SUP', text('not saved'));
  marker.dataset.editorDisplayOnly = 'true';
  const editor = new Element('DIV', text('one'), new Element('DIV', text('two')),
    new Element('DIV', new Element('BR')), new Element('DIV', text('three'), marker));
  assert.equal(drafts.editorPlainText(editor), 'one\ntwo\n\nthree');
  assert.equal(drafts.editorPlainText(new Element('DIV', text('a'), new Element('DIV', new Element('BR')))), 'a\n');
  assert.equal(drafts.editorPlainText(new Element('DIV', text('a'), new Element('BR'), text('b'))), 'a\nb');
} else if (scenario === 'selection_restore') {
  const item = makeEditor('a');
  const marker = new Element('SUP', text('1'));
  marker.dataset.editorDisplayOnly = 'true';
  const first = text('A😀');
  const last = text(' last');
  item.editor.childNodes = [first, marker, new Element('MARK', last)];
  let restored;
  sandbox.window.getSelection = () => ({setBaseAndExtent: (...args) => {restored = args;}});
  assert.equal(drafts.restoreEditorSelection({blockId: 'a', anchorOffset: 3, focusOffset: 6}), true);
  assert.deepEqual(restored, [first, 3, last, 3]);
  assert.equal(drafts.restoreEditorSelection({blockId: 'missing', anchorOffset: 0, focusOffset: 0}), false);
} else if (scenario === 'metadata_drafts') {
  const item = makeEditor('a');
  item.type.value = 'footnote';
  item.owner.value = 'owner';
  item.anchor.value = '4';
  drafts.recordBlockDraft(item.blockElement);
  assert.equal(state.reviewDrafts.get('a').type, 'footnote');
  assert.equal(state.reviewDrafts.get('a').footnoteOwner, 'owner');
  assert.equal(state.reviewDrafts.get('a').footnoteAnchor, '4');
  assert.equal(state.reviewDrafts.get('a').text, 'Original text');
  assert.equal(item.blockElement.classList.contains('is-dirty'), true);
  item.type.value = 'body';
  drafts.recordBlockDraft(item.blockElement);
  assert.equal(state.reviewDrafts.size, 0);
} else if (scenario === 'failed_save') {
  const {saveBlock} = await importModule('revisions.js');
  const item = makeEditor('a');
  changeText(item.editor, 'Unsaved edit');
  drafts.recordEditorDraft(item.editor);
  request = async () => {throw new Error('Failed local save');};
  await saveBlock(item.block, item.blockElement, item.editor, 'in_review', [item.button], item.message);
  assert.equal(state.reviewDrafts.get('a').text, 'Unsaved edit');
  assert.equal(state.reviewMutationPending, false);
  assert.equal(item.button.disabled, false);
  assert.equal(item.message.textContent, 'Failed local save');
  assert.equal(rendered.length, 0);
} else if (scenario === 'inflight_drafts') {
  const {saveBlock} = await importModule('revisions.js');
  const item = makeEditor('a');
  const other = makeEditor('b');
  changeText(item.editor, 'Submitted');
  const pending = deferred();
  let sent;
  request = async (_url, options) => {sent = JSON.parse(options.body); return pending.promise;};
  const saving = saveBlock(item.block, item.blockElement, item.editor, 'in_review', [item.button], item.message);
  assert.equal(sent.editorial_text, 'Submitted');
  // Reverting to the old server value while saving is still an unsaved change
  // relative to the newly submitted revision, even though captureDrafts is empty.
  changeText(item.editor, 'Original text');
  other.type.value = 'heading';
  pending.resolve({pages: [], translation_run_id: 'test-run'});
  await saving;
  assert.equal(rendered[0].drafts.get('a').text, 'Original text');
  assert.equal(rendered[0].drafts.get('b').type, 'heading');
  assert.equal(state.review.cost.total, 1);
} else if (scenario === 'concurrent_save') {
  const {saveBlock} = await importModule('revisions.js');
  const first = makeEditor('a');
  const second = makeEditor('b');
  const pending = deferred();
  let count = 0;
  request = async () => {count++; return pending.promise;};
  const saving = saveBlock(first.block, first.blockElement, first.editor, 'accepted', [first.button], first.message);
  await saveBlock(second.block, second.blockElement, second.editor, 'accepted', [second.button], second.message);
  assert.equal(count, 1);
  assert.equal(second.button.disabled, true);
  pending.resolve({pages: []});
  await saving;
  assert.equal(state.reviewDrafts.size, 0);
  assert.equal(state.reviewMutationPending, false);
} else if (scenario === 'uncertainty_drafts') {
  const {replaceUncertainty} = await importModule('uncertainties.js');
  const first = makeEditor('a');
  const second = makeEditor('b');
  second.type.value = 'heading';
  for (const item of [first, second]) {
    state.uncertaintyIndex.set(item.block.block_id, {block: item.block,
      page: {original_page_number: 1}, uncertainty: {uncertainty_id: item.block.block_id,
        highlight_mode: 'range', term_group_id: 'shared'}});
  }
  state.activeUncertaintyId = 'a';
  contextExports.replacementInput.value = 'replacement';
  let calls = 0;
  request = async () => {calls++;};
  await replaceUncertainty('all');
  assert.equal(calls, 0);
  assert.match(contextExports.replacementError.textContent, /Save the unsaved edits/);
  assert.equal(state.reviewDrafts.get('b').type, 'heading');
  assert.equal(state.reviewMutationPending, false);
} else if (['merged_page_navigation', 'short_final_page'].includes(scenario)) {
  const {reviewPageAnchor, navigateReviewPage, syncSourceToTranslation} = await importModule('pages.js');
  const scroller = contextExports.translationScroll;
  contextExports.reviewEditor.hidden = false;
  scroller.clientHeight = 600;
  scroller.scrollHeight = 1550;
  scroller.scrollTop = 0;
  state.reviewPages = [{original_page_number: 1}, {original_page_number: 2}];
  state.sourcePageNumber = 1;
  function anchor(page, position) {
    const element = new Element();
    element.dataset.pageNumber = String(page);
    element.getBoundingClientRect = () => ({top: position - scroller.scrollTop});
    return element;
  }
  const first = anchor(1, 0);
  const continuation = anchor(2, 700);
  const secondSection = anchor(2, 1000);
  translationContent.querySelector = (selector) => {
    const number = selector.match(/data-page-number="(\d+)"/)?.[1];
    return number === '2' ? continuation : first;
  };
  translationContent.querySelectorAll = (selector) => selector === '.review-page'
    ? [first, secondSection] : [first, continuation, secondSection];
  if (scenario === 'merged_page_navigation') {
    assert.equal(reviewPageAnchor(2), continuation);
    navigateReviewPage(2);
    assert.equal(scroller.scrollTop, 700, 'jump to the inline continuation before the later page section');
    assert.equal(state.sourcePageNumber, 2);
  } else {
    const finalStart = anchor(2, 1400);
    translationContent.querySelectorAll = () => [first, anchor(1, 500), finalStart];
    scroller.scrollTop = scroller.scrollHeight - scroller.clientHeight;
    syncSourceToTranslation();
    assert.equal(state.sourcePageNumber, 2, 'a short final page remains selected at clamped scroll end');
  }
} else if (scenario === 'unicode_footnote_offset') {
  const {handleReviewControlChange} = await importModule('events.js');
  const item = makeEditor('note');
  makeEditor('owner', 'A😀B');
  item.type.value = 'footnote';
  item.owner.value = 'owner';
  item.owner.dataset.action = 'change-footnote-owner';
  handleReviewControlChange({target: item.owner});
  assert.equal(item.anchor.max, '3');
  assert.equal(item.anchor.value, '3');
  assert.equal(state.reviewDrafts.get('note').footnoteAnchor, '3');
} else {
  throw new Error(`Unknown scenario: ${scenario}`);
}
