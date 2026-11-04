'use strict';

// All text from the API or the LLM reaches the page through textContent (see el()).
// Never build HTML strings here: LLM output is untrusted.

const MAX_REFINE_QUESTIONS = 3;
const VIEWER_BACKGROUND = '#0b1220';
const NGL_SCRIPT = {
    src: 'https://cdnjs.cloudflare.com/ajax/libs/ngl/2.3.1/ngl.js',
    integrity: 'sha384-2IGKSrhj5s8F8y255Khep26WxVFJnBmATKZAtfHE8/bCjEpyqsPNB9bEtbo+y5+P',
};
const SOURCE_LABELS = {
    ai: 'AI, verified in UniProt',
    curated: 'Curated',
    uniprot: 'UniProt match',
};
const RESULT_INTROS = {
    ai: 'Each AI suggestion was matched to a human UniProt entry by accession and name. The relevance and drug notes are AI-written, so verify them.',
    curated: "The AI didn't return usable results, so these come from the curated database.",
    uniprot: 'These are keyword matches from UniProt, so check that they fit your question.',
};
const QA_SECTIONS = {
    KEY: 'Key point',
    MECHANISM: 'Mechanism',
    CLINICAL: 'Clinical',
    WARNING: 'Caution',
    TIP: 'Tip',
};
const SUGGESTED_QUESTIONS = [
    'Why is this a drug target?',
    'What is its mechanism of action?',
    'Which diseases is it linked to?',
];

const state = {
    query: '',
    protein: null,
    structure: null,
    bestPdb: null,
    activeTab: '3dmol',
    loadId: 0,
    refine: null,
    viewers: {
        '3dmol': { instance: null, key: null, style: 'cartoon', color: 'spectrum' },
        ngl: { stage: null, component: null, key: null, style: 'cartoon' },
    },
};

const byId = (id) => document.getElementById(id);

// DOM helpers

function el(tag, props, ...children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([key, value]) => {
        if (value === undefined || value === null) return;
        if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else if (key === 'class') node.className = value;
        else if (key in node && key !== 'list') node[key] = value;
        else node.setAttribute(key, value);
    });
    node.append(...children.filter((child) => child !== null && child !== undefined));
    return node;
}

// Unlike replaceChildren alone, this skips null, which would otherwise show as the text "null".
function setChildren(node, ...children) {
    node.replaceChildren(...children.filter((child) => child !== null && child !== undefined));
}

function externalLink(label, href) {
    return el('a', { href, target: '_blank', rel: 'noopener noreferrer' }, label);
}

function scrollToEnd(node) {
    node.scrollTop = node.scrollHeight;
}

// API

async function postJSON(url, body) {
    let response;
    try {
        response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    } catch (error) {
        throw new Error('Could not reach the server. Check your connection and try again.');
    }

    let data = null;
    try {
        data = await response.json();
    } catch (error) {
        // Handled below: a proxy error page isn't JSON.
    }
    if (!response.ok || !data) {
        throw new Error((data && data.error) || `The server returned an error (${response.status}).`);
    }
    return data;
}

function selectedModel() {
    return byId('model-select').value;
}

// Chat

function addMessage(role, ...content) {
    const log = byId('chat-messages');
    const welcome = log.querySelector('.welcome');
    if (welcome) welcome.remove();
    const message = el('div', { class: `message ${role}` }, ...content);
    log.append(message);
    scrollToEnd(log);
    return message;
}

function addPending(label) {
    return addMessage('assistant', el('div', { class: 'pending' }, el('span', { class: 'dots', 'aria-hidden': 'true' }), label));
}

function setSearchBusy(busy, label) {
    const button = byId('send-btn');
    button.disabled = busy;
    button.textContent = busy ? label : 'Find targets';
}

async function runSearch(query) {
    state.query = query;
    state.refine = null;
    addMessage('user', query);
    setSearchBusy(true, 'Searching');
    const pending = addPending('Finding targets and checking them in UniProt');

    try {
        const data = await postJSON('/api/analyze', { prompt: query, model: selectedModel() });
        pending.remove();
        renderResults(data, true);
    } catch (error) {
        pending.remove();
        addMessage('assistant error', error.message);
    } finally {
        setSearchBusy(false);
    }
}

function proteinCard(protein) {
    const card = el(
        'button',
        {
            class: 'protein-card',
            type: 'button',
            'data-accession': protein.uniprot_id,
            onclick: () => loadProtein(protein),
        },
        el('span', { class: 'card-title' }, protein.name || 'Unknown protein'),
        el(
            'span',
            { class: 'card-meta' },
            [protein.gene, protein.uniprot_id, protein.length ? `${protein.length} aa` : null].filter(Boolean).join(' · ')
        ),
        protein.relevance ? el('span', { class: 'card-relevance' }, protein.relevance) : null,
        el('span', { class: `badge badge-${protein.source}` }, SOURCE_LABELS[protein.source] || 'Result')
    );
    if (state.protein && state.protein.uniprot_id === protein.uniprot_id) card.classList.add('selected');
    return card;
}

function renderResults(data, offerRefine) {
    const proteins = data.proteins || [];
    if (!proteins.length) {
        addMessage('assistant', "No human proteins matched that search. Try a specific disease or protein name.");
        return;
    }

    addMessage(
        'assistant',
        el('p', { class: 'result-intro' }, RESULT_INTROS[data.source] || ''),
        data.insights ? el('p', { class: 'insights' }, data.insights) : null,
        el('div', { class: 'protein-cards' }, ...proteins.map(proteinCard)),
        offerRefine
            ? el('button', { class: 'btn btn-quiet refine-start', type: 'button', onclick: (event) => startRefine(event.target) }, 'Narrow these results')
            : null
    );
}

// Guided refinement

function startRefine(button) {
    button.remove();
    state.refine = { query: state.query, answers: [], asked: 0 };
    askRefineQuestion();
}

async function askRefineQuestion() {
    const refine = state.refine;
    if (!refine) return;
    if (refine.asked >= MAX_REFINE_QUESTIONS) {
        finishRefine();
        return;
    }

    const pending = addPending('Thinking of a question');
    try {
        const data = await postJSON('/api/refine/question', {
            original_query: refine.query,
            answers: refine.answers,
            model: selectedModel(),
        });
        pending.remove();
        if (state.refine !== refine) return;
        refine.asked += 1;
        renderRefineQuestion(data.question);
    } catch (error) {
        pending.remove();
        addMessage('assistant error', error.message);
        state.refine = null;
    }
}

function renderRefineQuestion(question) {
    const input = el('input', { type: 'text', placeholder: 'Your answer', maxLength: 300, 'aria-label': question });
    const skip = el('button', { class: 'btn btn-quiet', type: 'button' }, 'Skip');
    const show = el('button', { class: 'btn btn-quiet', type: 'button' }, 'Show results');
    const submit = el('button', { class: 'btn btn-primary', type: 'submit' }, 'Answer');
    const form = el('form', { class: 'refine-form' }, input, el('div', { class: 'button-row' }, submit, skip, show));

    const retire = () => form.remove();

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const answer = input.value.trim();
        if (!answer) return;
        retire();
        addMessage('user', answer);
        state.refine.answers.push({ question, answer });
        askRefineQuestion();
    });
    skip.addEventListener('click', () => {
        retire();
        addMessage('user muted', 'Skipped');
        askRefineQuestion();
    });
    show.addEventListener('click', () => {
        retire();
        finishRefine();
    });

    addMessage('assistant', el('p', {}, question), form);
    input.focus();
}

async function finishRefine() {
    const refine = state.refine;
    state.refine = null;
    const pending = addPending('Searching UniProt with your answers');
    try {
        const { keywords } = await postJSON('/api/refine/keywords', {
            original_query: refine.query,
            answers: refine.answers,
            model: selectedModel(),
        });
        const data = await postJSON('/api/deep_search', { query: keywords });
        pending.remove();
        addMessage('assistant muted', `Search terms: ${keywords}`);
        renderResults(data, false);
    } catch (error) {
        pending.remove();
        addMessage('assistant error', error.message);
    }
}

// Protein loading

function markSelectedCards(accession) {
    document.querySelectorAll('.protein-card').forEach((card) => {
        card.classList.toggle('selected', card.dataset.accession === accession);
    });
}

function setStageMessage(title, text, isError) {
    ['3dmol', 'ngl'].forEach((name) => {
        const box = byId(`message-${name}`);
        if (!title) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        box.classList.toggle('error', Boolean(isError));
        box.replaceChildren(el('h3', {}, title), text ? el('p', {}, text) : '');
    });
}

function clearViewers() {
    const mol = state.viewers['3dmol'];
    if (mol.instance) mol.instance.clear();
    mol.key = null;

    const ngl = state.viewers.ngl;
    if (ngl.stage) ngl.stage.removeAllComponents();
    ngl.component = null;
    ngl.key = null;

    byId('plddt-legend').hidden = true;
    byId('controls-3dmol').hidden = true;
    byId('controls-ngl').hidden = true;
}

async function loadProtein(protein, source) {
    const loadId = ++state.loadId;
    const isNewProtein = !state.protein || state.protein.uniprot_id !== protein.uniprot_id;

    state.protein = protein;
    state.structure = null;
    markSelectedCards(protein.uniprot_id);
    renderProteinBar(protein);
    if (isNewProtein) resetQA(protein);
    renderDetails(protein);

    clearViewers();
    setStageMessage('Loading structure', null);
    if (state.activeTab === 'info' || state.activeTab === 'ask') switchTab('3dmol');
    // The panels are stacked on small screens, so the viewer may be offscreen.
    if (window.matchMedia('(max-width: 900px)').matches) {
        document.querySelector('.viewer-panel').scrollIntoView({ behavior: 'smooth' });
    }

    try {
        const data = await postJSON('/api/structure', { uniprot_id: protein.uniprot_id, source });
        if (loadId !== state.loadId) return;

        const merged = {
            ...data.protein,
            relevance: protein.relevance,
            drugs: protein.drugs,
            source: protein.source,
        };
        state.protein = merged;
        state.structure = data.structure;
        state.bestPdb = data.best_pdb;
        renderProteinBar(merged);
        renderDetails(merged);

        if (!data.structure) {
            setStageMessage('No 3D structure available', "AlphaFold DB and RCSB PDB don't have a usable model for this protein.");
            return;
        }
        setStageMessage(null);
        renderActiveViewer();
    } catch (error) {
        if (loadId !== state.loadId) return;
        setStageMessage('Could not load the structure', error.message, true);
    }
}

function renderProteinBar(protein) {
    byId('protein-bar').hidden = false;
    byId('protein-title').textContent = protein.name || 'Unknown protein';
    const structureLabel = state.structure ? state.structure.label : null;
    byId('protein-subtitle').textContent = [protein.gene, protein.uniprot_id, structureLabel].filter(Boolean).join(' · ');

    const toggle = byId('source-switch');
    const bothSources = Boolean(state.structure && state.bestPdb);
    toggle.hidden = !bothSources;
    if (!bothSources) return;
    byId('pdb-source-btn').textContent = `PDB ${state.bestPdb.id}`;
    toggle.querySelectorAll('.segment').forEach((button) => {
        const active = button.dataset.source === state.structure.source;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
    });
}

// Tabs

function switchTab(name) {
    state.activeTab = name;
    document.querySelectorAll('.tab').forEach((tab) => {
        const selected = tab.dataset.tab === name;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
    });
    document.querySelectorAll('.tab-pane').forEach((pane) => {
        pane.classList.toggle('active', pane.id === `tab-${name}`);
    });
    renderActiveViewer();
}

function renderActiveViewer() {
    if (state.activeTab === '3dmol') render3Dmol();
    else if (state.activeTab === 'ngl') renderNGL();
}

function structureKey() {
    return state.structure && state.protein ? `${state.protein.uniprot_id}:${state.structure.source}` : null;
}

function downloadStructure() {
    if (!state.structure) return;
    const blob = new Blob([state.structure.pdb_data], { type: 'chemical/x-pdb' });
    const url = URL.createObjectURL(blob);
    const link = el('a', { href: url, download: `${state.protein.uniprot_id}_${state.structure.source}.pdb` });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function toolbarGroup(label, options, current, onSelect) {
    return el(
        'div',
        { class: 'tool-group', role: 'group', 'aria-label': label },
        el('span', { class: 'tool-label' }, label),
        ...options.map(([value, text]) => {
            const active = value === current;
            return el(
                'button',
                {
                    class: `segment${active ? ' active' : ''}`,
                    type: 'button',
                    'aria-pressed': String(active),
                    onclick: () => onSelect(value),
                },
                text
            );
        })
    );
}

// 3Dmol viewer

function plddtColor(atom) {
    if (atom.b >= 90) return '#0053d6';
    if (atom.b >= 70) return '#65cbf3';
    if (atom.b >= 50) return '#ffdb13';
    return '#ff7d45';
}

function apply3DmolStyle() {
    const view = state.viewers['3dmol'];
    const viewer = view.instance;
    const useConfidence = view.color === 'confidence';
    const color = useConfidence ? { colorfunc: plddtColor } : { color: 'spectrum' };

    viewer.removeAllSurfaces();
    if (view.style === 'sticks') {
        viewer.setStyle({}, { stick: useConfidence ? { colorfunc: plddtColor, radius: 0.2 } : { colorscheme: 'Jmol', radius: 0.2 } });
    } else if (view.style === 'spheres') {
        viewer.setStyle({}, { sphere: useConfidence ? { colorfunc: plddtColor } : { colorscheme: 'Jmol' } });
    } else {
        viewer.setStyle({}, { cartoon: color });
    }
    if (view.style === 'surface') {
        viewer.addSurface($3Dmol.SurfaceType.VDW, { opacity: 0.55, color: '#e2e8f0' });
    }
    viewer.render();

    const legend = byId('plddt-legend');
    legend.hidden = !useConfidence;
    if (useConfidence && state.structure.mean_plddt) {
        byId('plddt-mean').textContent = `Mean ${state.structure.mean_plddt.toFixed(1)}`;
    }
}

function render3DmolControls() {
    const view = state.viewers['3dmol'];
    const isPrediction = state.structure.source === 'alphafold';
    const rerender = (key) => (value) => {
        view[key] = value;
        apply3DmolStyle();
        render3DmolControls();
    };

    const bar = byId('controls-3dmol');
    bar.hidden = false;
    setChildren(
        bar,
        toolbarGroup(
            'Style',
            [['cartoon', 'Cartoon'], ['surface', 'Surface'], ['sticks', 'Sticks'], ['spheres', 'Spheres']],
            view.style,
            rerender('style')
        ),
        isPrediction
            ? toolbarGroup('Color', [['confidence', 'Confidence'], ['spectrum', 'Rainbow']], view.color, rerender('color'))
            : null,
        el(
            'div',
            { class: 'tool-group tool-actions' },
            el('button', { class: 'btn btn-quiet', type: 'button', onclick: () => { view.instance.zoomTo(); view.instance.render(); } }, 'Reset view'),
            el('button', { class: 'btn btn-quiet', type: 'button', onclick: downloadStructure }, 'Download PDB')
        )
    );
}

function render3Dmol() {
    const view = state.viewers['3dmol'];
    const key = structureKey();
    if (!key || typeof $3Dmol === 'undefined') {
        if (key) setStageMessage('The 3D viewer could not load', 'Check your connection, then reload the page.', true);
        return;
    }

    if (!view.instance) {
        view.instance = $3Dmol.createViewer(byId('viewer-3dmol'), { backgroundColor: VIEWER_BACKGROUND, antialias: true });
    }
    if (view.key === key) {
        view.instance.resize();
        view.instance.render();
        return;
    }

    view.key = key;
    view.style = 'cartoon';
    view.color = state.structure.source === 'alphafold' ? 'confidence' : 'spectrum';
    view.instance.clear();
    view.instance.addModel(state.structure.pdb_data, 'pdb');
    view.instance.resize();
    apply3DmolStyle();
    view.instance.zoomTo();
    view.instance.render();
    render3DmolControls();
}

// NGL viewer, loaded the first time its tab opens because the library is 1.3 MB

let nglLoading = null;

function loadNGL() {
    if (typeof NGL !== 'undefined') return Promise.resolve();
    if (!nglLoading) {
        nglLoading = new Promise((resolve, reject) => {
            const script = el('script', { src: NGL_SCRIPT.src, integrity: NGL_SCRIPT.integrity, crossOrigin: 'anonymous' });
            script.onload = resolve;
            script.onerror = () => {
                nglLoading = null;
                reject(new Error('The NGL viewer could not load.'));
            };
            document.head.append(script);
        });
    }
    return nglLoading;
}

function applyNGLStyle() {
    const view = state.viewers.ngl;
    if (!view.component) return;
    view.component.removeAllRepresentations();
    if (view.style === 'surface') {
        view.component.addRepresentation('surface', { color: 'residueindex', opacity: 0.8 });
    } else if (view.style === 'ballstick') {
        view.component.addRepresentation('ball+stick', { color: 'element' });
    } else if (view.style === 'spacefill') {
        view.component.addRepresentation('spacefill', { color: 'element' });
    } else {
        view.component.addRepresentation('cartoon', { color: 'residueindex' });
    }
}

function renderNGLControls() {
    const view = state.viewers.ngl;
    const bar = byId('controls-ngl');
    bar.hidden = false;
    bar.replaceChildren(
        toolbarGroup(
            'Style',
            [['cartoon', 'Cartoon'], ['surface', 'Surface'], ['ballstick', 'Ball and stick'], ['spacefill', 'Spacefill']],
            view.style,
            (value) => {
                view.style = value;
                applyNGLStyle();
                renderNGLControls();
            }
        ),
        el(
            'div',
            { class: 'tool-group tool-actions' },
            el('button', { class: 'btn btn-quiet', type: 'button', onclick: () => view.component && view.component.autoView() }, 'Reset view'),
            el('button', { class: 'btn btn-quiet', type: 'button', onclick: downloadStructure }, 'Download PDB')
        )
    );
}

async function renderNGL() {
    const view = state.viewers.ngl;
    const key = structureKey();
    if (!key) return;

    if (view.key === key) {
        if (view.stage) view.stage.handleResize();
        return;
    }
    view.key = key;

    try {
        await loadNGL();
        if (view.key !== key) return;
        if (!view.stage) {
            view.stage = new NGL.Stage(byId('viewer-ngl'), { backgroundColor: VIEWER_BACKGROUND });
        }
        view.stage.removeAllComponents();
        view.stage.handleResize();
        const blob = new Blob([state.structure.pdb_data], { type: 'text/plain' });
        const component = await view.stage.loadFile(blob, { ext: 'pdb' });
        if (view.key !== key) return;
        view.component = component;
        view.style = 'cartoon';
        applyNGLStyle();
        component.autoView();
        renderNGLControls();
    } catch (error) {
        view.key = null;
        const box = byId('message-ngl');
        box.hidden = false;
        box.classList.add('error');
        box.replaceChildren(el('h3', {}, 'The NGL viewer could not load'), el('p', {}, 'Use the 3D view tab instead, or reload the page.'));
    }
}

// Details tab

function section(title, ...content) {
    return el('section', { class: 'detail-section' }, el('h4', {}, title), ...content);
}

function renderDetails(protein) {
    const accession = protein.uniprot_id;
    const links = [
        externalLink('UniProt', `https://www.uniprot.org/uniprotkb/${encodeURIComponent(accession)}/entry`),
        externalLink('AlphaFold DB', `https://alphafold.ebi.ac.uk/entry/${encodeURIComponent(accession)}`),
    ];
    if (state.bestPdb && state.structure) {
        links.push(externalLink(`RCSB ${state.bestPdb.id}`, `https://www.rcsb.org/structure/${encodeURIComponent(state.bestPdb.id)}`));
    }
    links.push(externalLink('Open Targets', `https://platform.opentargets.org/search?q=${encodeURIComponent(protein.gene || accession)}`));

    const facts = [
        ['Accession', accession],
        ['Gene', protein.gene],
        ['Organism', protein.organism],
        ['Length', protein.length ? `${protein.length} residues` : null],
        ['Structure', state.structure ? state.structure.label : null],
    ].filter(([, value]) => value);

    setChildren(
        byId('protein-info'),
        el('h3', {}, protein.name || 'Unknown protein'),
        el('span', { class: `badge badge-${protein.source}` }, SOURCE_LABELS[protein.source] || 'Result'),
        el('dl', { class: 'facts' }, ...facts.flatMap(([term, value]) => [el('dt', {}, term), el('dd', {}, value)])),
        protein.relevance ? section('Why it may matter', el('p', {}, protein.relevance)) : null,
        protein.function ? section('Function (UniProt)', el('p', {}, protein.function)) : null,
        protein.diseases && protein.diseases.length
            ? section('Disease associations (UniProt)', el('ul', {}, ...protein.diseases.map((name) => el('li', {}, name))))
            : null,
        protein.drugs
            ? section(
                protein.source === 'ai' ? 'Drugs (AI-suggested, verify before use)' : 'Drugs (curated)',
                el('p', {}, protein.drugs)
            )
            : null,
        section('Explore further', el('div', { class: 'link-row' }, ...links))
    );
}

// Ask AI tab

function resetQA(protein) {
    const askAbout = (question) => {
        byId('qa-input').value = question;
        sendQuestion();
    };
    byId('qa-messages').replaceChildren(
        el(
            'div',
            { class: 'empty-state' },
            el('h3', {}, `Ask about ${protein.name || 'this protein'}`),
            el('p', {}, 'Answers use the UniProt record as context, but they can still be wrong.'),
            el(
                'div',
                { class: 'chips' },
                ...SUGGESTED_QUESTIONS.map((question) =>
                    el('button', { class: 'chip', type: 'button', onclick: () => askAbout(question) }, question)
                )
            )
        )
    );
    byId('qa-input').disabled = false;
    byId('qa-send-btn').disabled = false;
}

// Adds **bold** text as real elements, so model output can't inject markup.
function inlineNodes(text) {
    return text.split(/\*\*(.+?)\*\*/g).map((part, index) => (index % 2 ? el('strong', {}, part) : document.createTextNode(part)));
}

function blockNodes(text) {
    const nodes = [];
    let list = null;
    text.split('\n').forEach((rawLine) => {
        const line = rawLine.trim();
        if (!line) {
            list = null;
            return;
        }
        const bullet = line.match(/^[-*•]\s+(.*)$/);
        if (bullet) {
            if (!list) {
                list = el('ul');
                nodes.push(list);
            }
            list.append(el('li', {}, ...inlineNodes(bullet[1])));
        } else {
            list = null;
            nodes.push(el('p', {}, ...inlineNodes(line)));
        }
    });
    return nodes;
}

function formatAnswer(text) {
    const cleaned = text.replace(/\[\/(KEY|MECHANISM|CLINICAL|WARNING|TIP)\]/g, '');
    const parts = cleaned.split(/\[(KEY|MECHANISM|CLINICAL|WARNING|TIP)\]:?/);
    const nodes = blockNodes(parts[0]);
    for (let i = 1; i < parts.length; i += 2) {
        const tag = parts[i];
        nodes.push(
            el(
                'div',
                { class: `qa-section qa-${tag.toLowerCase()}` },
                el('span', { class: 'qa-label' }, QA_SECTIONS[tag]),
                ...blockNodes(parts[i + 1] || '')
            )
        );
    }
    return nodes;
}

function addQAMessage(role, ...content) {
    const log = byId('qa-messages');
    const emptyState = log.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    const message = el('div', { class: `message ${role}` }, ...content);
    log.append(message);
    scrollToEnd(log);
    return message;
}

async function sendQuestion() {
    const input = byId('qa-input');
    const question = input.value.trim();
    const protein = state.protein;
    if (!question || !protein) return;

    input.value = '';
    addQAMessage('user', question);
    const button = byId('qa-send-btn');
    button.disabled = true;
    const pending = addQAMessage(
        'assistant',
        el('div', { class: 'pending' }, el('span', { class: 'dots', 'aria-hidden': 'true' }), 'Thinking')
    );

    try {
        const data = await postJSON('/api/ask', {
            uniprot_id: protein.uniprot_id,
            question,
            model: selectedModel(),
            context: { relevance: protein.relevance, drugs: protein.drugs },
        });
        pending.remove();
        if (state.protein && state.protein.uniprot_id === protein.uniprot_id) {
            addQAMessage('assistant', ...formatAnswer(data.response));
        }
    } catch (error) {
        pending.remove();
        addQAMessage('assistant error', error.message);
    } finally {
        button.disabled = false;
    }
}

// Theme

function currentTheme() {
    const explicit = document.documentElement.dataset.theme;
    if (explicit) return explicit;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function updateThemeButton() {
    byId('theme-toggle').textContent = currentTheme() === 'dark' ? 'Light theme' : 'Dark theme';
}

function toggleTheme() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
        localStorage.setItem('theme', next);
    } catch (error) {
        // Storage can be blocked. The theme still applies for this visit.
    }
    updateThemeButton();
}

// Startup

function updateModelNote() {
    const select = byId('model-select');
    byId('model-info').textContent = select.options[select.selectedIndex].dataset.note || '';
}

function submitSearch() {
    const input = byId('chat-input');
    const query = input.value.trim();
    if (!query || byId('send-btn').disabled) return;
    input.value = '';
    runSearch(query);
}

function handleTabKeys(event) {
    const tabs = Array.from(document.querySelectorAll('.tab'));
    const index = tabs.indexOf(document.activeElement);
    if (index === -1) return;
    let next = null;
    if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
    if (next) {
        event.preventDefault();
        next.focus();
        switchTab(next.dataset.tab);
    }
}

function init() {
    byId('search-form').addEventListener('submit', (event) => {
        event.preventDefault();
        submitSearch();
    });
    byId('chat-input').addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submitSearch();
        }
    });
    byId('example-queries').addEventListener('click', (event) => {
        if (event.target.matches('.chip')) runSearch(event.target.textContent);
    });

    byId('qa-form').addEventListener('submit', (event) => {
        event.preventDefault();
        sendQuestion();
    });

    document.querySelectorAll('.tab').forEach((tab) => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });
    document.querySelector('.tabs').addEventListener('keydown', handleTabKeys);

    byId('source-switch').addEventListener('click', (event) => {
        const button = event.target.closest('.segment');
        if (!button || !state.protein || !state.structure) return;
        if (button.dataset.source !== state.structure.source) {
            loadProtein(state.protein, button.dataset.source === 'pdb' ? 'pdb' : 'auto');
        }
    });

    byId('model-select').addEventListener('change', updateModelNote);
    byId('theme-toggle').addEventListener('click', toggleTheme);
    updateModelNote();
    updateThemeButton();

    window.addEventListener('resize', () => {
        const mol = state.viewers['3dmol'];
        if (state.activeTab === '3dmol' && mol.instance) mol.instance.resize();
        const ngl = state.viewers.ngl;
        if (state.activeTab === 'ngl' && ngl.stage) ngl.stage.handleResize();
    });
}

init();
