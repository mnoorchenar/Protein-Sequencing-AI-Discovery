---
title: biomedical-protein-target-explorer
colorFrom: blue
colorTo: indigo
sdk: docker
---

<div align="center">

<h1>🧬 Biomedical Protein Target Explorer</h1>
<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=22&duration=3000&pause=1000&color=4F46E5&center=true&vCenter=true&width=700&lines=AI-Powered+Drug+Target+Discovery;Protein+Structure+Visualization;UniProt+%26+AlphaFold+Integration;Built+for+Biomedical+Research" alt="Typing SVG"/>

<br/>

[![Python](https://img.shields.io/badge/Python-3.10+-3b82f6?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.x-4f46e5?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-3b82f6?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Status](https://img.shields.io/badge/Status-Active-22c55e?style=for-the-badge)](#)

<br/>

[![Live Demo](https://img.shields.io/badge/%E2%96%B6_Live_Demo-Hugging_Face_Space-ffcc00?style=for-the-badge&logo=huggingface&logoColor=black)](https://huggingface.co/spaces/mnoorchenar/Protein-Sequencing-AI-Discovery)
[![Source Code](https://img.shields.io/badge/Source_Code-GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/mnoorchenar/Protein-Sequencing-AI-Discovery)

<br/>

**🧬 Biomedical Protein Target Explorer** — An AI-powered web application that identifies relevant human protein targets for drug discovery from natural language research queries, enriches them with live UniProt metadata, and renders interactive 3D protein structures from AlphaFold and PDB.

<br/>

---

</div>

## Table of Contents

- [Features](#-features)
- [Architecture](#️-architecture)
- [Getting Started](#-getting-started)
- [Docker Deployment](#-docker-deployment)
- [Dashboard Modules](#-dashboard-modules)
- [ML Models](#-ml-models)
- [Project Structure](#-project-structure)
- [Author](#-author)
- [Contributing](#-contributing)
- [Disclaimer](#️-disclaimer)
- [License](#-license)

---

## ✨ Features

<table>
  <tr>
    <td>🤖 <b>AI Target Identification</b></td>
    <td>Uses large language models via HuggingFace Inference API to extract 3–5 relevant human protein targets from free-text biomedical queries, with automatic multi-model fallback</td>
  </tr>
  <tr>
    <td>🔬 <b>3D Structure Visualization</b></td>
    <td>Fetches and renders protein structures interactively from AlphaFold DB and RCSB PDB; falls back to a generated demo helix when no structure is available</td>
  </tr>
  <tr>
    <td>🔎 <b>UniProt Deep Search</b></td>
    <td>Directly queries the UniProt REST API for reviewed human proteins (organism ID 9606), returning function, disease associations, sequence length, and accession data</td>
  </tr>
  <tr>
    <td>💬 <b>Protein Q&A Chat</b></td>
    <td>Context-aware biomedical chat endpoint that answers user questions about specific proteins or general drug discovery concepts using the same multi-model LLM pipeline</td>
  </tr>
  <tr>
    <td>🔒 <b>Secure by Design</b></td>
    <td>HuggingFace token passed via environment variable; no user data stored; all external datasets are public APIs</td>
  </tr>
  <tr>
    <td>🐳 <b>Containerized Deployment</b></td>
    <td>Docker-first architecture targeting port 7860, fully compatible with HuggingFace Spaces docker SDK</td>
  </tr>
</table>

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│              Biomedical Protein Target Explorer                  │
│                                                                  │
│  ┌─────────────────┐   ┌──────────────────┐  ┌──────────────┐  │
│  │  User Query     │──▶│  HuggingFace LLM │─▶│  JSON Parser │  │
│  │  (NL Text)      │   │  Inference API   │  │  + Filter    │  │
│  └─────────────────┘   └──────────────────┘  └──────┬───────┘  │
│                                                       │          │
│  ┌─────────────────┐   ┌──────────────────┐          │          │
│  │  UniProt REST   │◀──│  Protein IDs     │◀─────────┘          │
│  │  API (metadata) │   │  (UniProt Acc.)  │                     │
│  └────────┬────────┘   └──────────────────┘                     │
│           │                                                      │
│  ┌────────▼────────┐   ┌──────────────────┐                     │
│  │  AlphaFold DB   │   │  Flask API       │                     │
│  │  / RCSB PDB     │──▶│  Backend         │                     │
│  │  (PDB files)    │   │  (app.py)        │                     │
│  └─────────────────┘   └────────┬─────────┘                     │
│                                 │                                │
│                        ┌────────▼─────────┐                     │
│                        │  HTML/JS/CSS     │                     │
│                        │  Frontend        │                     │
│                        └──────────────────┘                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Git
- HuggingFace account (free) for LLM inference

### Local Installation

```bash
# 1. Clone the repository
git clone https://github.com/mnoorchenar/Protein-Sequencing-AI-Discovery.git
cd Protein-Sequencing-AI-Discovery

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python app.py
```

Open your browser at `http://localhost:7860` 🎉

---

## 🐳 Docker Deployment

```bash

# Or build and run manually
docker build -t Protein-Sequencing-AI-Discovery .
docker run -p 7860:7860 -e HF_TOKEN=your_token_here Protein-Sequencing-AI-Discovery
```

---

## 📊 Dashboard Modules

| Module | Description | Status |
|--------|-------------|--------|
| 🤖 AI Protein Finder | Submit a natural language research query; LLM returns structured human protein targets with UniProt IDs | ✅ Live |
| 🔬 Structure Viewer | Interactive 3D molecular viewer powered by AlphaFold DB and RCSB PDB lookups per UniProt accession | ✅ Live |
| 🔎 UniProt Deep Search | Direct keyword search against the UniProt REST API filtered to reviewed human proteins (organism 9606) | ✅ Live |
| 💬 Protein Q&A Chat | Ask follow-up questions about any returned protein; context-aware biomedical responses from LLM | ✅ Live |
| 📚 Curated Fallback DB | Disease-to-protein mapping loaded from `disease_proteins.json`; activates only when all LLM models fail | 🔄 Beta |
| 🧪 Drug Association Panel | Surface known drugs per protein target from cross-referenced clinical and UniProt annotation data | 🗓️ Planned |

---

## 🧠 ML Models

```python
# LLM models used in Biomedical Protein Target Explorer
# Queried via HuggingFace InferenceClient with automatic fallback

models = {
    "primary":    "mistralai/Mistral-7B-Instruct-v0.3",
    "fallback_1": "meta-llama/Llama-3.2-3B-Instruct",
    "fallback_2": "microsoft/Phi-3-mini-4k-instruct",
    "fallback_3": "ServiceNow-AI/Apriel-5B-Instruct",
    "fallback_4": "prithivMLmods/Llama-3.1-5B-Instruct"
}
```

> **Note:** All models are accessed through the HuggingFace Inference API — no local GPU required. The app tries each model in sequence until a valid structured response is returned.

---

## 📁 Project Structure

```
Protein-Sequencing-AI-Discovery/
│
├── 📂 static/                    # CSS, JavaScript & assets
│   ├── script.js
│   └── style.css
├── 📂 templates/                 # HTML templates
│   └── index.html
├── 📄 Dockerfile                 # Container definition (port 7860, HF Spaces ready)
├── 📄 app.py                     # Application entry point — all routes & logic
├── 📄 disease_proteins.json      # Curated fallback database (disease → human proteins)
└── 📄 requirements.txt           # Python dependencies
```

---

## 👨‍💻 Author

<div align="center">

<table>
<tr>
<td align="center" width="100%">

<img src="https://avatars.githubusercontent.com/mnoorchenar" width="120" style="border-radius:50%; border: 3px solid #4f46e5;" alt="Mohammad Noorchenarboo"/>

<h3>Mohammad Noorchenarboo</h3>

<code>Data Scientist</code> &nbsp;|&nbsp; <code>AI Researcher</code> &nbsp;|&nbsp; <code>Biostatistician</code>

📍 &nbsp;Ontario, Canada &nbsp;&nbsp; 📧 &nbsp;[mohammadnoorchenarboo@gmail.com](mailto:mohammadnoorchenarboo@gmail.com)

──────────────────────────────────────

[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mnoorchenar)&nbsp;
[![Personal Site](https://img.shields.io/badge/Website-mnoorchenar.github.io-4f46e5?style=for-the-badge&logo=githubpages&logoColor=white)](https://mnoorchenar.github.io/)&nbsp;
[![HuggingFace](https://img.shields.io/badge/HuggingFace-ffcc00?style=for-the-badge&logo=huggingface&logoColor=black)](https://huggingface.co/mnoorchenar)&nbsp;
[![Google Scholar](https://img.shields.io/badge/Scholar-4285F4?style=for-the-badge&logo=googlescholar&logoColor=white)](https://scholar.google.ca/citations?user=nn_Toq0AAAAJ&hl=en)&nbsp;
[![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/mnoorchenar)

</td>
</tr>
</table>

</div>

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing-feature`
3. **Commit** your changes: `git commit -m 'Add amazing feature'`
4. **Push** to the branch: `git push origin feature/amazing-feature`
5. **Open** a Pull Request

---

## ⚠️ Disclaimer

> [!WARNING]
> This project is developed strictly for educational and research purposes and does not constitute professional medical, clinical, or pharmaceutical advice of any kind. All protein and structural data is retrieved from publicly available databases (UniProt, AlphaFold DB, RCSB PDB). No real patient or proprietary data is stored or processed. LLM-generated protein suggestions should be independently verified before use in any research context. This software is provided "as is" without warranty of any kind; use at your own risk.

---

## 📜 License

Distributed under the **MIT License**.

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:3b82f6,100:4f46e5&height=120&section=footer&text=Made%20with%20%E2%9D%A4%EF%B8%8F%20by%20Mohammad%20Noorchenarboo&fontColor=ffffff&fontSize=18&fontAlignY=80" width="100%"/>

[![GitHub Stars](https://img.shields.io/github/stars/mnoorchenar/Protein-Sequencing-AI-Discovery?style=social)](https://github.com/mnoorchenar/Protein-Sequencing-AI-Discovery/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/mnoorchenar/Protein-Sequencing-AI-Discovery?style=social)](https://github.com/mnoorchenar/Protein-Sequencing-AI-Discovery/fork)

<sub>The name "Biomedical Protein Target Explorer" is used purely for academic and research purposes. Any similarity to existing product names or trademarks is entirely coincidental. This project has no affiliation with any commercial entity.</sub>

</div>
