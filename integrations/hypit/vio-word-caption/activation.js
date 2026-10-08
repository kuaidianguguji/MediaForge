// Trusted application component. User text is data in VisualElement, never HTML/JS.
import { assertAttributes, assertEmptyElement, canonicalize, createMarkupSurfaceHostFacet,
  sameType, sealGraphFragment, textAttribute } from '@hypit/hypit/author-kit';
import { compositionTypes, sealVisualTrack } from '@hypit/hypit/composition';
import { mediaTypes } from '@hypit/hypit/media';
import { timelineTypes } from '@hypit/hypit/timeline';
import { spatialTypes } from '@hypit/hypit/spatial';
import { browserProgram } from '@hypit/hypit/hyperframes';

const module = { name: '@vio/vio-word-caption', version: '1' };
const optionsType = { module, name: 'CaptionOptions' };
const producer = { module, name: 'render' };
const value = data => ({ kind: 'inline', value: canonicalize(data) });
const inline = record => {
  if (record?.value.kind !== 'inline') throw new Error('Caption requires inline inputs.');
  return record.value.value;
};
const manifest = { format: 'hypit.module@1', ...module,
  dependencies: [compositionTypes.visualTrack, mediaTypes.fontArtifact, timelineTypes.track, spatialTypes.canvas]
    .map(type => ({ module: type.module })),
  types: [{ name: optionsType.name }], capabilities: [], producers: [{ name: producer.name,
    inputs: [{ name: 'timeline', type: timelineTypes.track }, { name: 'canvas', type: spatialTypes.canvas },
      { name: 'font', type: mediaTypes.fontArtifact }, { name: 'options', type: optionsType }],
    outputs: [{ name: 'track', type: compositionTypes.visualTrack }], needs: [] }],
};

function captionTrack(timeline, canvas, font, options) {
  const fps = timeline.frameRate.numerator / timeline.frameRate.denominator;
  const frameCount = Math.round(timeline.durationSec * fps);
  const groups = options.groups;
  const size = Math.max(20, Math.round(canvas.widthPx * .052));
  const elements = groups.flatMap((group, groupIndex) => group.items.map((item, index) => ({
    id: `g${groupIndex}w${index}`, parent: 'captions', kind: 'text', order: groupIndex * 100 + index + 1,
    text: item.word, fonts: [font], style: [{ name: 'font-size', value: `${size}px` },
      { name: 'line-height', value: 1.25 },
      { name: 'color', value: '#FFFFFF' }],
  })));
  const program = browserProgram({
    html: groups.map((group, gi) => `<div class="cue" data-group="${gi}">${group.items.map((_, wi) =>
      `<span data-word="${wi}">{{g${gi}w${wi}}}</span>`).join(' ')}</div>`).join(''),
    css: `:scope{position:absolute;inset:0;pointer-events:none}.cue{position:absolute;left:7%;right:7%;bottom:10%;text-align:center;line-height:1.25;display:none;white-space:normal;text-shadow:0 2px 3px #000,2px 0 3px #000,-2px 0 3px #000,0 -2px 3px #000}.cue>span{display:inline-block;padding:1px 2px;border-radius:3px;background:#00000088}`,
    data: { groups: groups.map(group => ({ start: Math.round(group.start * fps), end: Math.round(group.end * fps),
      words: group.items.map(item => ({ start: Math.round(item.start * fps), end: Math.round(item.end * fps) })) })),
      highlight: options.style === 'highlight' },
    setup: `const cues=[...root.querySelectorAll('.cue')];return frame=>{cues.forEach((cue,i)=>{const group=data.groups[i];cue.style.display=frame>=group.start&&frame<group.end?'block':'none';[...cue.children].forEach((node,j)=>{const word=group.words[j];node.style.background=data.highlight&&frame>=word.start&&frame<word.end?'#166c57':'#00000088';});});};`,
  });
  return sealVisualTrack({ id: options.id, programSpaceId: timeline.id, visualIr: 'hypit.visual-ir@1',
    presents: [{ id: options.id, span: { startFrame: 0, endFrameExclusive: frameCount },
      stacking: { order: 90, tieBreak: options.id }, elements: [{ id: 'captions', kind: 'program', order: 0,
        program, style: [{ name: 'position', value: 'absolute' }, { name: 'inset', value: 0 },
          { name: 'width', value: `${canvas.widthPx}px` }, { name: 'height', value: `${canvas.heightPx}px` }] }, ...elements] }] });
}

const handler = ({ element, resolveReference }) => {
  assertAttributes(element, ['id', 'timeline', 'canvas', 'font', 'groups', 'style']);
  assertEmptyElement(element);
  const id = textAttribute(element, 'id');
  const reference = (name, type) => {
    const raw = element.attributes[name];
    if (typeof raw !== 'object' || raw.kind !== 'reference') throw new Error(`${name} must be a reference.`);
    const found = resolveReference(raw.path);
    if (!found || !sameType(found.type, type)) throw new Error(`${name} has the wrong type.`);
    return found;
  };
  const options = { id, style: textAttribute(element, 'style'), groups: JSON.parse(textAttribute(element, 'groups')) };
  if (!['highlight', 'plain'].includes(options.style) || !Array.isArray(options.groups)) throw new Error('Invalid caption options.');
  const fragment = sealGraphFragment({ inputs: manifest.producers[0].inputs,
    operations: [{ id: 'render', producer, inputs: Object.fromEntries(['timeline', 'canvas', 'font', 'options']
      .map(name => [name, { kind: 'fragment-input', name }])), result: { kind: 'output', name: 'track' } }],
    exports: [{ name: 'track', type: compositionTypes.visualTrack, root: { kind: 'fragment-operation', operation: 'render' } }] });
  return { records: [{ id: `${id}.options`, type: optionsType, value: value(options), range: element.range }],
    fragments: [fragment], components: [{ id, fragment: fragment.id, inputs: {
      timeline: reference('timeline', timelineTypes.track).ref, canvas: reference('canvas', spatialTypes.canvas).ref,
      font: reference('font', mediaTypes.fontArtifact).ref, options: { kind: 'record', id: `${id}.options` } },
      outputs: { track: `${id}.track` }, range: element.range }], exports: [`${id}.track`] };
};

export const hypitPackage = { format: 'hypit.node-package@1', modules: [{ manifest }],
  components: [{ producers: [{ producer, handler: ({ inputs }) => ({ outputs: {
    track: value(captionTrack(inline(inputs.timeline), inline(inputs.canvas), inline(inputs.font), inline(inputs.options))) }, needs: {} }) }] }],
  hostFacets: [createMarkupSurfaceHostFacet({ module, declaration: { name: 'captions', tag: 'Track', mode: 'structured',
    outputs: [compositionTypes.visualTrack, optionsType], vocabulary: { summary: 'Application-owned measured word captions.',
      attributes: ['id', 'timeline', 'canvas', 'font', 'groups', 'style'].map(name => ({ name, kind: 'expression', required: true, summary: name })),
      ports: [{ name: 'track', type: compositionTypes.visualTrack, summary: 'Word captions visual track.' }] } }, handler })],
};
export default hypitPackage;
