// Global State
let appState = {
    currentViewer: '3dmol',
    currentProtein: null,
    currentPDBData: null,
    viewerInstances: {},
    proteins: [],
    selectedModel: 'mistralai/Mistral-7B-Instruct-v0.3',
    lastQuery: '',
    deepSearchMode: false,
    deepSearchStep: 0,
    deepSearchContext: {}
};

const modelDescriptions = {
    'mistralai/Mistral-7B-Instruct-v0.3': 'Balanced quality & speed',
    'mistralai/Mistral-7B-Instruct-v0.2': 'Previous Mistral version',
    'mistralai/Mixtral-8x7B-Instruct-v0.1': 'Best quality, slower response',
    'meta-llama/Meta-Llama-3-8B-Instruct': 'Latest Llama, excellent reasoning',
    'meta-llama/Llama-2-7b-chat-hf': 'Good general purpose',
    'meta-llama/Llama-2-13b-chat-hf': 'Larger model, better quality',
    'microsoft/BioGPT-Large': 'Specialized for biology & medicine',
    'HuggingFaceH4/zephyr-7b-beta': 'High quality open model',
    'tiiuae/falcon-7b-instruct': 'Fast and efficient',
    'google/flan-t5-xxl': 'Good for structured tasks',
    'microsoft/phi-2': 'Small, fast, efficient'
};

// Tab Switching
function switchTab(tabName) {
    document.querySelectorAll('.viewer-tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
    
    document.querySelector('[data-tab="' + tabName + '"]').classList.add('active');
    document.getElementById('tab-' + tabName).classList.add('active');
    
    appState.currentViewer = tabName;
    
    if (appState.currentPDBData && ['3dmol', 'ngl', 'simple'].includes(tabName)) {
        displayProteinStructure(appState.currentPDBData);
    }
}

// Send Message
function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    
    if (!message) return;
    
    appState.lastQuery = message;
    addMessage('user', message);
    input.value = '';
    
    const sendBtn = document.getElementById('send-btn');
    sendBtn.disabled = true;
    sendBtn.textContent = '🔬 Analyzing...';
    
    fetch('/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt: message,
            hf_token: '',
            model: appState.selectedModel
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            addMessage('assistant', 'Error: ' + data.error);
        } else if (data.no_results) {
            displayNoResults(appState.lastQuery);
        } else if (data.proteins && data.proteins.length > 0) {
            appState.proteins = data.proteins;
            displayProteinResults(data.proteins);
        } else {
            displayNoResults(appState.lastQuery);
        }
    })
    .catch(error => {
        addMessage('assistant', 'Error: ' + error.message);
    })
    .finally(() => {
        sendBtn.disabled = false;
        sendBtn.textContent = '🔬 Discover Proteins';
    });
}

// Add Message
function addMessage(role, content) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message ' + role;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = content;
    
    messageDiv.appendChild(contentDiv);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Display Protein Results
function displayProteinResults(proteins) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    if (!proteins || proteins.length === 0) {
        contentDiv.innerHTML = '<strong>No proteins found.</strong>';
        messageDiv.appendChild(contentDiv);
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        return;
    }
    
    const resultText = appState.deepSearchMode ? 
        'Based on your answers, here are the most relevant proteins:' :
        'Found ' + proteins.length + ' proteins. Click for details:';
    
    contentDiv.innerHTML = '<strong>' + resultText + '</strong>';
    
    const boxesDiv = document.createElement('div');
    boxesDiv.className = 'protein-boxes';
    
    proteins.forEach(function(protein, idx) {
        const box = document.createElement('div');
        box.className = 'protein-box';
        box.innerHTML = '<strong>' + (idx + 1) + '. ' + (protein.name || 'Unknown Protein') + '</strong><small>ID: ' + (protein.uniprot_id || 'N/A') + '</small>';
        box.onclick = function() { loadProtein(protein); };
        boxesDiv.appendChild(box);
    });
    
    contentDiv.appendChild(boxesDiv);
    
    if (!appState.deepSearchMode) {
        const deepSearchBtn = document.createElement('button');
        deepSearchBtn.className = 'deep-search-btn';
        deepSearchBtn.textContent = '💬 Want Better Results? Try Deep Search';
        deepSearchBtn.style.marginTop = '15px';
        deepSearchBtn.onclick = function() { startDeepSearch(); };
        contentDiv.appendChild(deepSearchBtn);
    }
    
    messageDiv.appendChild(contentDiv);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    appState.deepSearchMode = false;
    appState.deepSearchStep = 0;
}

// Display No Results
function displayNoResults(query) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = '<strong>🔍 Searching UniProt database...</strong>';
    
    messageDiv.appendChild(contentDiv);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    // Automatically trigger deep search
    deepSearch(query);
}

// Deep Search (UniProt)
function deepSearch(query) {
    const buttons = document.querySelectorAll('.deep-search-btn');
    buttons.forEach(btn => {
        btn.disabled = true;
        btn.textContent = '🔍 Searching UniProt...';
    });
    
    fetch('/deep_search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            addMessage('assistant', 'Deep Search Error: ' + data.error);
        } else if (data.proteins && data.proteins.length > 0) {
            appState.proteins = data.proteins;
            displayProteinResults(data.proteins);
        } else {
            addMessage('assistant', 'No proteins found in UniProt database for this query. Try rephrasing your search.');
        }
    })
    .catch(error => {
        addMessage('assistant', 'Deep Search Error: ' + error.message);
    })
    .finally(() => {
        buttons.forEach(btn => {
            btn.disabled = false;
            btn.textContent = '🔍 Deep Search';
        });
    });
}

// Start Deep Search Conversation
function startDeepSearch() {
    appState.deepSearchMode = true;
    appState.deepSearchStep = 1;
    appState.deepSearchContext = {
        originalQuery: appState.lastQuery,
        answers: []
    };
    
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    const deepBox = document.createElement('div');
    deepBox.className = 'deep-search-mode';
    
    const modeText = document.createElement('p');
    modeText.textContent = '🔍 Deep Search Mode Activated';
    deepBox.appendChild(modeText);
    
    const infoText = document.createElement('p');
    infoText.textContent = 'I will ask you a few questions to find the perfect proteins...';
    infoText.style.fontWeight = 'normal';
    infoText.style.fontSize = '0.85em';
    deepBox.appendChild(infoText);
    
    contentDiv.appendChild(deepBox);
    messageDiv.appendChild(contentDiv);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    askDeepSearchQuestion();
}

// Ask Deep Search Question
function askDeepSearchQuestion() {
    const sendBtn = document.getElementById('send-btn');
    sendBtn.disabled = true;
    sendBtn.textContent = '🤔 Thinking...';
    
    const context = appState.deepSearchContext;
    const conversationHistory = context.answers.map(function(a) {
        return 'Q: ' + a.question + '\nA: ' + a.answer;
    }).join('\n\n');
    
    // After collecting answers (max 5 questions), generate search query from LLM
    if (appState.deepSearchStep > 5) {
        // Generate refined search query based on conversation
        generateSearchQueryFromConversation();
        return;
    }
    
    // Ask clarifying questions (steps 1-5)
    const prompt = 'You are helping refine a protein search. Original query: "' + context.originalQuery + '"\n\n' +
        'Previous conversation:\n' + (conversationHistory || 'None yet') + '\n\n' +
        'Current step: ' + appState.deepSearchStep + ' of 5\n\n' +
        'Task: Ask ONE specific clarifying question to narrow down the protein search. ' +
        'Make it relevant to the disease, mechanism, pathway, or specific protein characteristics. ' +
        'Be concise and specific. Examples:\n' +
        '- "Are you interested in proteins involved in apoptosis or cell proliferation?"\n' +
        '- "Do you want to focus on receptor proteins or signaling molecules?"\n' +
        '- "Are you looking for therapeutic targets or biomarkers?"\n\n' +
        'Respond with ONLY the question, nothing else.';
    
    fetch('/chat_question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt: prompt,
            model: appState.selectedModel
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.response) {
            displayDeepSearchQuestion(data.response);
        } else {
            addMessage('assistant', 'Error in deep search. Showing quick results instead.');
            appState.deepSearchMode = false;
        }
    })
    .catch(error => {
        addMessage('assistant', 'Error: ' + error.message);
        appState.deepSearchMode = false;
    })
    .finally(() => {
        sendBtn.disabled = false;
        sendBtn.textContent = '🔬 Discover Proteins';
    });
}

// Generate Search Query from Conversation
function generateSearchQueryFromConversation() {
    const context = appState.deepSearchContext;
    const conversationHistory = context.answers.map(function(a) {
        return 'Q: ' + a.question + '\nA: ' + a.answer;
    }).join('\n\n');
    
    const prompt = 'You are a biomedical search expert. Analyze this conversation and extract the best UniProt search keywords.\n\n' +
        'Original query: "' + context.originalQuery + '"\n\n' +
        'Conversation:\n' + conversationHistory + '\n\n' +
        'CRITICAL TASK: Extract the core scientific concepts from the user\'s answers and create a precise search query.\n' +
        'Rules:\n' +
        '1. Ignore conversational words like "yes", "no", "I want", "please", etc.\n' +
        '2. Extract only scientific terms: diseases, proteins, pathways, mechanisms\n' +
        '3. Combine original query context with user preferences\n' +
        '4. Use 4-7 precise biomedical keywords\n' +
        '5. Use terms that UniProt database will understand\n\n' +
        'Examples of GOOD queries:\n' +
        '- "breast cancer metastasis EMT epithelial mesenchymal"\n' +
        '- "Alzheimer disease amyloid beta tau phosphorylation"\n' +
        '- "diabetes type 2 insulin resistance GLUT4"\n' +
        '- "lung cancer EGFR tyrosine kinase mutation"\n\n' +
        'Examples of BAD queries (never do this):\n' +
        '- "yes metastasis proteins please" ❌\n' +
        '- "I want apoptosis related" ❌\n' +
        '- "give me cancer targets" ❌\n\n' +
        'Respond ONLY with: "SEARCH_READY: [keywords]"\n' +
        'Example: "SEARCH_READY: breast cancer HER2 receptor tyrosine kinase metastasis"';
    
    fetch('/chat_question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt: prompt,
            model: appState.selectedModel
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.response && data.response.includes('SEARCH_READY:')) {
            const searchTerms = data.response.replace('SEARCH_READY:', '').trim();
            // Clean up any remaining conversational words
            const cleanedTerms = searchTerms.replace(/\b(yes|no|please|I want|give me|show me)\b/gi, '').trim();
            performRefinedSearch(cleanedTerms);
        } else {
            // Fallback: use original query
            performRefinedSearch(context.originalQuery);
        }
    })
    .catch(error => {
        performRefinedSearch(context.originalQuery);
    });
}

// Display Deep Search Question
function displayDeepSearchQuestion(question) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = '<strong>' + question + '</strong>';
    
    const inputArea = document.createElement('div');
    inputArea.className = 'question-input-area';
    
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Your answer...';
    input.id = 'deep-search-answer';
    input.style.marginBottom = '10px';
    input.style.width = '100%';
    inputArea.appendChild(input);
    
    // First button row - Submit and Skip
    const firstButtonRow = document.createElement('div');
    firstButtonRow.style.display = 'flex';
    firstButtonRow.style.gap = '10px';
    firstButtonRow.style.alignItems = 'stretch';
    firstButtonRow.style.width = '100%';
    firstButtonRow.style.marginBottom = '10px';
    
    const submitBtn = document.createElement('button');
    submitBtn.textContent = 'Submit Answer';
    submitBtn.style.flex = '1';
    submitBtn.style.padding = '10px 15px';
    submitBtn.style.borderRadius = '5px';
    submitBtn.style.cursor = 'pointer';
    submitBtn.onclick = function() { submitDeepSearchAnswer(question, input.value); };
    firstButtonRow.appendChild(submitBtn);
    
    const skipBtn = document.createElement('button');
    skipBtn.textContent = '⏭️ Skip';
    skipBtn.className = 'skip-question-btn';
    skipBtn.style.background = '#ff9800';
    skipBtn.style.color = 'white';
    skipBtn.style.border = 'none';
    skipBtn.style.padding = '10px 15px';
    skipBtn.style.borderRadius = '5px';
    skipBtn.style.cursor = 'pointer';
    skipBtn.style.flex = '1';
    skipBtn.style.whiteSpace = 'nowrap';
    skipBtn.onclick = function() {
        addMessage('user', '[Question skipped]');
        appState.deepSearchStep++;
        askDeepSearchQuestion();
    };
    firstButtonRow.appendChild(skipBtn);
    
    inputArea.appendChild(firstButtonRow);
    
    // Second button row - Show Results
    const secondButtonRow = document.createElement('div');
    secondButtonRow.style.display = 'flex';
    secondButtonRow.style.width = '100%';
    
    const showResultsBtn = document.createElement('button');
    showResultsBtn.textContent = '📊 Show Results';
    showResultsBtn.className = 'show-results-btn';
    showResultsBtn.style.background = '#4caf50';
    showResultsBtn.style.color = 'white';
    showResultsBtn.style.border = 'none';
    showResultsBtn.style.padding = '10px 15px';
    showResultsBtn.style.borderRadius = '5px';
    showResultsBtn.style.cursor = 'pointer';
    showResultsBtn.style.width = '100%';
    showResultsBtn.onclick = function() {
        skipToSearch();
    };
    secondButtonRow.appendChild(showResultsBtn);
    
    inputArea.appendChild(secondButtonRow);
    contentDiv.appendChild(inputArea);
    messageDiv.appendChild(contentDiv);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    input.focus();
    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            submitDeepSearchAnswer(question, input.value);
        }
    });
}

// Submit Deep Search Answer
function submitDeepSearchAnswer(question, answer) {
    if (!answer.trim()) return;
    
    addMessage('user', answer);
    
    appState.deepSearchContext.answers.push({
        question: question,
        answer: answer
    });
    
    appState.deepSearchStep++;
    
    // Always continue to next question until we get SEARCH_READY response
    askDeepSearchQuestion();
}

// Skip to Search
function skipToSearch() {
    addMessage('assistant', '⏭️ Generating search query based on current information...');
    
    const context = appState.deepSearchContext;
    
    // If no answers yet, use original query
    if (context.answers.length === 0) {
        performRefinedSearch(context.originalQuery);
        return;
    }
    
    const conversationHistory = context.answers.map(function(a) {
        return 'Q: ' + a.question + '\nA: ' + a.answer;
    }).join('\n\n');
    
    const prompt = 'Based on this conversation, generate a refined UniProt search query.\n\n' +
        'Original query: "' + context.originalQuery + '"\n' +
        'Conversation:\n' + conversationHistory + '\n\n' +
        'Respond ONLY with: "SEARCH_READY: [keywords]" ' +
        'where keywords are 3-6 precise biomedical terms. ' +
        'Examples: "SEARCH_READY: breast cancer HER2 receptor", ' +
        '"SEARCH_READY: Alzheimer amyloid beta protein". ' +
        'Use only scientific keywords, no conversational words.';
    
    fetch('/chat_question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt: prompt,
            model: appState.selectedModel
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.response && data.response.startsWith('SEARCH_READY:')) {
            const searchTerms = data.response.replace('SEARCH_READY:', '').trim();
            performRefinedSearch(searchTerms);
        } else {
            // Fallback: use original query + answers
            const allText = context.originalQuery + ' ' + context.answers.map(a => a.answer).join(' ');
            performRefinedSearch(allText);
        }
    })
    .catch(error => {
        addMessage('assistant', 'Error: ' + error.message);
        appState.deepSearchMode = false;
    });
}

// Perform Refined Search
function performRefinedSearch(searchTerms) {
    addMessage('assistant', '🔍 Searching with refined criteria: "' + searchTerms + '"');
    
    fetch('/deep_search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchTerms })
    })
    .then(response => response.json())
    .then(data => {
        if (data.proteins && data.proteins.length > 0) {
            appState.proteins = data.proteins.slice(0, 5);
            displayProteinResults(appState.proteins);
        } else {
            addMessage('assistant', 'No specific matches found. Try rephrasing or use quick search.');
            appState.deepSearchMode = false;
        }
    })
    .catch(error => {
        addMessage('assistant', 'Search error: ' + error.message);
        appState.deepSearchMode = false;
    });
}

// Load Protein
function loadProtein(protein) {
    appState.currentProtein = protein;
    
    document.getElementById('qa-messages').innerHTML = '<div class="welcome-message"><h3>💬 Ask Questions About ' + (protein.name || 'This Protein') + '</h3><p>I can explain mechanisms, clinical relevance, structure features, and more!</p></div>';
    document.getElementById('qa-input').disabled = false;
    document.getElementById('qa-send-btn').disabled = false;
    
    const viewer = document.getElementById('protein-viewer');
    viewer.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading structure...</p></div>';
    
    fetch('/get_structure', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uniprot_id: protein.uniprot_id })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            viewer.innerHTML = '<div class="loading"><p style="color: #f44336;">' + data.error + '</p></div>';
        } else {
            appState.currentPDBData = data;
            displayProteinStructure(data);
            displayProteinInfo(protein, data);
            initializeControls();
        }
    })
    .catch(error => {
        viewer.innerHTML = '<div class="loading"><p style="color: #f44336;">Error: ' + error.message + '</p></div>';
    });
}

// Display Protein Structure
function displayProteinStructure(data) {
    if (appState.currentViewer === '3dmol') {
        init3DmolViewer(data.pdb_data);
    } else if (appState.currentViewer === 'ngl') {
        initNGLViewer(data.pdb_data);
    } else if (appState.currentViewer === 'simple') {
        initSimpleViewer(data.pdb_data);
    }
}

// 3Dmol Viewer
function init3DmolViewer(pdbData) {
    const container = document.getElementById('protein-viewer');
    container.innerHTML = '';
    
    const config = { backgroundColor: 'black' };
    const viewer = $3Dmol.createViewer(container, config);
    
    viewer.addModel(pdbData, 'pdb');
    viewer.setStyle({}, { cartoon: { color: 'spectrum' } });
    viewer.zoomTo();
    viewer.render();
    viewer.zoom(0.8, 1000);
    
    appState.viewerInstances['3dmol'] = viewer;
}

// NGL Viewer
function initNGLViewer(pdbData) {
    const container = document.getElementById('protein-viewer-ngl');
    container.innerHTML = '';
    
    const stage = new NGL.Stage(container, { backgroundColor: 'black' });
    
    const blob = new Blob([pdbData], { type: 'text/plain' });
    stage.loadFile(blob, { ext: 'pdb' }).then(function(component) {
        component.addRepresentation('cartoon', { color: 'chainname' });
        component.autoView();
        appState.viewerInstances['ngl'] = { stage: stage, component: component };
    });
}

// Simple Viewer (Three.js)
function initSimpleViewer(pdbData) {
    const container = document.getElementById('protein-viewer-simple');
    container.innerHTML = '';
    
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);
    
    const camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.z = 50;
    
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);
    
    const atoms = parsePDB(pdbData);
    const protein = createProteinMesh(atoms);
    scene.add(protein);
    
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);
    
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(1, 1, 1);
    scene.add(directionalLight);
    
    appState.viewerInstances['simple'] = { scene: scene, camera: camera, renderer: renderer, protein: protein, autoRotate: true };
    
    function animate() {
        requestAnimationFrame(animate);
        if (appState.viewerInstances['simple'].autoRotate) {
            protein.rotation.y += 0.005;
            protein.rotation.x += 0.002;
        }
        renderer.render(scene, camera);
    }
    animate();
}

function parsePDB(pdbData) {
    const atoms = [];
    const lines = pdbData.split('\n');
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.startsWith('ATOM')) {
            const x = parseFloat(line.substring(30, 38));
            const y = parseFloat(line.substring(38, 46));
            const z = parseFloat(line.substring(46, 54));
            const element = line.substring(76, 78).trim();
            
            if (!isNaN(x) && !isNaN(y) && !isNaN(z)) {
                atoms.push({ x: x, y: y, z: z, element: element });
            }
        }
    }
    return atoms;
}

function createProteinMesh(atoms) {
    const group = new THREE.Group();
    
    if (atoms.length === 0) {
        const geometry = new THREE.TorusKnotGeometry(10, 3, 100, 16);
        const material = new THREE.MeshPhongMaterial({ color: 0x667eea });
        return new THREE.Mesh(geometry, material);
    }
    
    const geometry = new THREE.SphereGeometry(0.5, 8, 8);
    const sampleRate = Math.max(1, Math.floor(atoms.length / 1000));
    
    for (let i = 0; i < atoms.length; i += sampleRate) {
        const atom = atoms[i];
        const color = getAtomColor(atom.element);
        const material = new THREE.MeshPhongMaterial({ color: color });
        const sphere = new THREE.Mesh(geometry, material);
        sphere.position.set(atom.x, atom.y, atom.z);
        group.add(sphere);
    }
    
    const box = new THREE.Box3().setFromObject(group);
    const center = box.getCenter(new THREE.Vector3());
    group.position.sub(center);
    
    return group;
}

function getAtomColor(element) {
    const colors = {
        'C': 0x909090, 'N': 0x3050F8, 'O': 0xFF0D0D,
        'S': 0xFFFF30, 'H': 0xFFFFFF
    };
    return colors[element] || 0x667eea;
}

// Initialize Controls
function initializeControls() {
    const controls = {
        '3dmol': ['Cartoon', 'Surface', 'Stick', 'Sphere', 'Reset'],
        'ngl': ['Cartoon', 'Surface', 'Ball+Stick', 'Spacefill', 'Reset'],
        'simple': ['Reset', 'Toggle Rotation', 'Zoom In', 'Zoom Out']
    };
    
    ['3dmol', 'ngl', 'simple'].forEach(function(viewer) {
        const container = document.getElementById('controls-' + viewer);
        container.innerHTML = '';
        
        controls[viewer].forEach(function(ctrl) {
            const btn = document.createElement('button');
            btn.className = 'control-btn';
            btn.textContent = ctrl;
            btn.onclick = function() { handleControl(viewer, ctrl); };
            container.appendChild(btn);
        });
    });
}

// Handle Control
function handleControl(viewer, control) {
    if (viewer === '3dmol') {
        const v = appState.viewerInstances['3dmol'];
        if (!v) return;
        
        v.setStyle({}, {});
        
        if (control === 'Cartoon') {
            v.setStyle({}, { cartoon: { color: 'spectrum' } });
        } else if (control === 'Surface') {
            v.setStyle({}, { cartoon: { color: 'spectrum' } });
            v.addSurface($3Dmol.SurfaceType.VDW, { opacity: 0.7, color: 'white' });
        } else if (control === 'Stick') {
            v.setStyle({}, { stick: { colorscheme: 'Jmol' } });
        } else if (control === 'Sphere') {
            v.setStyle({}, { sphere: { colorscheme: 'Jmol' } });
        } else if (control === 'Reset') {
            v.setStyle({}, { cartoon: { color: 'spectrum' } });
            v.zoomTo();
        }
        v.render();
    } else if (viewer === 'ngl') {
        const instance = appState.viewerInstances['ngl'];
        if (!instance) return;
        
        const component = instance.component;
        component.removeAllRepresentations();
        
        if (control === 'Cartoon') {
            component.addRepresentation('cartoon', { color: 'chainname' });
        } else if (control === 'Surface') {
            component.addRepresentation('surface', { opacity: 0.7 });
        } else if (control === 'Ball+Stick') {
            component.addRepresentation('ball+stick');
        } else if (control === 'Spacefill') {
            component.addRepresentation('spacefill');
        } else if (control === 'Reset') {
            component.addRepresentation('cartoon', { color: 'chainname' });
            component.autoView();
        }
    } else if (viewer === 'simple') {
        const instance = appState.viewerInstances['simple'];
        if (!instance) return;
        
        if (control === 'Reset') {
            instance.camera.position.set(0, 0, 50);
            instance.protein.rotation.set(0, 0, 0);
        } else if (control === 'Toggle Rotation') {
            instance.autoRotate = !instance.autoRotate;
        } else if (control === 'Zoom In') {
            instance.camera.position.z = Math.max(10, instance.camera.position.z - 5);
        } else if (control === 'Zoom Out') {
            instance.camera.position.z = Math.min(100, instance.camera.position.z + 5);
        }
    }
}

// Display Protein Info
function displayProteinInfo(protein, data) {
    if (!protein || !data) return;
    
    const infoDiv = document.getElementById('protein-info');
    if (!infoDiv) return;
    
    const proteinName = protein.name || 'Unknown Protein';
    const organism = data.organism || 'Unknown';
    const length = data.length || 'Unknown';
    const relevance = protein.relevance || 'Protein of interest';
    const proteinFunction = protein.function || 'Function information not available';
    const drugs = protein.drugs || null;
    const uniprotId = data.uniprot_id || 'N/A';
    const confidence = data.confidence || 'Unknown';
    
    infoDiv.innerHTML = '<h3>🧬 ' + proteinName + '</h3>' +
        '<div class="info-box" style="background: #e8f5e9; border-left-color: #4caf50;">' +
        '<h4 style="color: #2e7d32;">🔍 Quick Overview</h4>' +
        '<p>' + proteinName + ' is a protein found in ' + organism + ' with ' + length + ' amino acids.</p>' +
        '<p><strong>Why it matters:</strong> ' + relevance + '</p>' +
        '</div>' +
        '<h4 style="margin-top: 25px;">🔬 Molecular Details</h4>' +
        '<p><strong>UniProt ID:</strong> ' + uniprotId + '</p>' +
        '<p><strong>Sequence Length:</strong> ' + length + ' residues</p>' +
        '<p><strong>Organism:</strong> ' + organism + '</p>' +
        '<p><strong>Structure Source:</strong> ' + confidence + '</p>' +
        '<h4 style="margin-top: 25px;">⚙️ Function & Mechanism</h4>' +
        '<p>' + proteinFunction + '</p>' +
        (drugs ? '<div class="info-box" style="background: #fff3e0; border-left-color: #ff9800;"><h4 style="color: #e65100;">💊 Therapeutic Agents</h4><p><strong>Known drugs:</strong> ' + drugs + '</p><p style="font-size: 0.9em; margin-top: 10px;">These agents work by modulating protein activity through various mechanisms including competitive inhibition, allosteric regulation, or direct binding.</p></div>' : '') +
        '<h4 style="margin-top: 25px;">🎯 3D Structure Analysis</h4>' +
        '<p>The visualization shows the protein folded 3D conformation. Key features to observe:</p>' +
        '<ul style="margin-left: 20px; margin-top: 10px;">' +
        '<li><strong>Secondary structures:</strong> Alpha-helices (spiral regions) and beta-sheets (flat regions)</li>' +
        '<li><strong>Active sites:</strong> Pocket-like cavities that may serve as drug binding sites</li>' +
        '<li><strong>Surface properties:</strong> Regions that interact with other molecules</li>' +
        '</ul>' +
        '<div class="info-box" style="background: #e3f2fd; border-left-color: #2196f3; margin-top: 15px;"><h4 style="color: #1565c0;">💡 Pro Tip</h4><p>Try different visualization modes (Cartoon, Surface, Stick) to explore various structural aspects. Switch to the "💬 Ask Questions" tab to learn more!</p></div>';
}

// Send Protein Question
function sendProteinQuestion() {
    const input = document.getElementById('qa-input');
    const question = input.value.trim();
    
    if (!question || !appState.currentProtein) return;
    
    addQAMessage('user', question);
    input.value = '';
    
    const sendBtn = document.getElementById('qa-send-btn');
    sendBtn.disabled = true;
    sendBtn.textContent = '🤔 Thinking...';
    
    const protein = appState.currentProtein;
    const data = appState.currentPDBData;
    
    // Optimized prompt for concise, structured responses under 500 tokens
    const systemPrompt = 'You are a biomedical expert. Answer CONCISELY in under 400 words.\n\n' +
        'Protein: ' + (protein.name || 'Unknown') + '\n' +
        'Function: ' + (protein.function || 'N/A') + '\n' +
        'Clinical Relevance: ' + (protein.relevance || 'N/A') + '\n' +
        'Known Drugs: ' + (protein.drugs || 'None') + '\n' +
        'Organism: ' + (data ? data.organism : 'N/A') + '\n' +
        'Length: ' + (data ? data.length : 'N/A') + ' amino acids\n\n' +
        'RULES:\n' +
        '- Answer ONLY the specific question asked\n' +
        '- Be direct and to-the-point, no extra information\n' +
        '- Use natural emojis (🧬 💊 ⚡ 🎯 ⚠️ ✅) to enhance readability\n' +
        '- Structure your answer with these tags when appropriate:\n' +
        '  [KEY] for main answer\n' +
        '  [MECHANISM] for how it works\n' +
        '  [CLINICAL] for medical relevance\n' +
        '  [WARNING] for important cautions\n' +
        '  [TIP] for helpful insights\n' +
        '- Keep each section 1-3 sentences MAX\n' +
        '- Use **bold** for important terms\n\n' +
        'Question: ' + question + '\n\n' +
        'Answer (under 400 words):';
    
    const tokenInput = document.getElementById('hf-token-input');
    const userToken = tokenInput ? tokenInput.value.trim() : '';
    
    fetch('/chat_question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt: systemPrompt,
            model: appState.selectedModel,
            hf_token: userToken
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.response) {
            addQAMessage('bot', data.response);
        } else if (data.error) {
            addQAMessage('bot', '⚠️ Error: ' + data.error + '\n\nPlease try rephrasing your question.');
        } else {
            addQAMessage('bot', '⚠️ Unable to generate response. The AI model may be temporarily unavailable. Please try again in a moment.');
        }
    })
    .catch(error => {
        addQAMessage('bot', '❌ Connection error: ' + error.message + '\n\nPlease check your connection and try again.');
    })
    .finally(() => {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send Question';
    });
}

// Add QA Message
function addQAMessage(role, content) {
    const messagesDiv = document.getElementById('qa-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'qa-message ' + (role === 'user' ? 'user-qa' : 'bot-qa');
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'qa-message-content';
    
    if (role === 'bot') {
        contentDiv.innerHTML = formatQAResponse(content);
    } else {
        contentDiv.textContent = content;
    }
    
    messageDiv.appendChild(contentDiv);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Format QA Response
function formatQAResponse(text) {
    let formatted = text;

    // Handle tags WITHOUT closing tags (single line format)
    // Match [TAG] at start of line followed by content until end of line or next tag
    formatted = formatted.replace(/\[KEY\]\s*(.*?)(?=\n\[|$)/gs, '<div class="qa-key-box">🎯 <strong>Key Point:</strong> $1</div>');
    formatted = formatted.replace(/\[MECHANISM\]\s*(.*?)(?=\n\[|$)/gs, '<div class="qa-mechanism-box">⚡ <strong>Mechanism:</strong> $1</div>');
    formatted = formatted.replace(/\[CLINICAL\]\s*(.*?)(?=\n\[|$)/gs, '<div class="qa-clinical-box">💊 <strong>Clinical:</strong> $1</div>');
    formatted = formatted.replace(/\[WARNING\]\s*(.*?)(?=\n\[|$)/gs, '<div class="qa-warning-box">⚠️ <strong>Warning:</strong> $1</div>');
    formatted = formatted.replace(/\[TIP\]\s*(.*?)(?=\n\[|$)/gs, '<div class="qa-tip-box">💡 <strong>Tip:</strong> $1</div>');
    
    // Handle tags WITH closing tags (wrapped format)
    formatted = formatted.replace(/\[KEY\](.*?)\[\/KEY\]/gs, '<div class="qa-key-box">🎯 <strong>Key Point:</strong> $1</div>');
    formatted = formatted.replace(/\[MECHANISM\](.*?)\[\/MECHANISM\]/gs, '<div class="qa-mechanism-box">⚡ <strong>Mechanism:</strong> $1</div>');
    formatted = formatted.replace(/\[CLINICAL\](.*?)\[\/CLINICAL\]/gs, '<div class="qa-clinical-box">💊 <strong>Clinical:</strong> $1</div>');
    formatted = formatted.replace(/\[WARNING\](.*?)\[\/WARNING\]/gs, '<div class="qa-warning-box">⚠️ <strong>Warning:</strong> $1</div>');
    formatted = formatted.replace(/\[TIP\](.*?)\[\/TIP\]/gs, '<div class="qa-tip-box">💡 <strong>Tip:</strong> $1</div>');
    
    // Legacy tags support
    formatted = formatted.replace(/\[HIGHLIGHT\](.*?)\[\/HIGHLIGHT\]/gs, '<div class="qa-key-box">✅ $1</div>');
    formatted = formatted.replace(/\[INFO\](.*?)\[\/INFO\]/gs, '<div class="qa-tip-box">ℹ️ $1</div>');

    // Bold text
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Bullet points
    formatted = formatted.replace(/^- (.+)$/gm, '<li>$1</li>');
    formatted = formatted.replace(/(<li>.*<\/li>\n?)+/g, match => '<ul>' + match + '</ul>');
    
    // Paragraphs (only for text NOT already in divs)
    formatted = formatted.replace(/\n\n/g, '</p><p>');
    
    // Wrap only if not starting with a div
    if (!formatted.trim().startsWith('<div')) {
        formatted = '<p>' + formatted + '</p>';
    }

    return formatted;
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('send-btn').addEventListener('click', sendMessage);

    document.getElementById('chat-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    document.querySelectorAll('.viewer-tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            switchTab(this.getAttribute('data-tab'));
        });
    });

    document.getElementById('model-select').addEventListener('change', function() {
        appState.selectedModel = this.value;
        const info = document.getElementById('model-info');
        if (info) {
            info.textContent = modelDescriptions[this.value] || 'Model selected';
        }
    });

    document.getElementById('qa-send-btn').addEventListener('click', sendProteinQuestion);

    document.getElementById('qa-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            sendProteinQuestion();
        }
    });
});