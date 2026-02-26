from flask import Flask, render_template, request, jsonify
import requests
import json
import re
import os
from huggingface_hub import InferenceClient

# Get HF token from environment
DEFAULT_HF_TOKEN = os.environ.get('HF_TOKEN', '')

# Initialize InferenceClient GLOBALLY
client = InferenceClient(token=DEFAULT_HF_TOKEN if DEFAULT_HF_TOKEN else None)

app = Flask(__name__)

# Load disease-protein database from JSON file
def load_disease_protein_database():
    """Load disease-protein database from JSON file"""
    json_file = 'disease_proteins.json'
    
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r') as f:
                database = json.load(f)
                print(f"✅ Loaded disease database with {len(database)} diseases")
                return database
        except Exception as e:
            print(f"❌ Error loading disease database: {e}")
            return {}
    else:
        print(f"⚠️ Warning: {json_file} not found. Fallback database disabled.")
        return {}

# Load database at startup
DISEASE_PROTEIN_DATABASE = load_disease_protein_database()

def query_huggingface(prompt, model, hf_token=None, use_system_prompt=True):
    """Query HF API using InferenceClient with automatic fallback"""

    # Use global client or create new one if user token provided
    if hf_token and hf_token != DEFAULT_HF_TOKEN:
        request_client = InferenceClient(token=hf_token)
    else:
        request_client = client
    
    # Optimized fallback list
    fallback_models = [
        model,
    "meta-llama/Llama-3.2-3B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "microsoft/Phi-3-mini-4k-instruct",
    "ServiceNow-AI/Apriel-5B-Instruct",
    "prithivMLmods/Llama-3.1-5B-Instruct"
    ]
    
    # Remove duplicates
    seen = set()
    fallback_models = [m for m in fallback_models if not (m in seen or seen.add(m))]
    
    if use_system_prompt and "You are a biomedical" not in prompt:
        system_prompt = """You are a biomedical AI assistant specialized in drug discovery. 
        Given a user's research query, identify 3-5 relevant HUMAN protein targets for drug development.
        
        CRITICAL REQUIREMENTS:
        - Focus ONLY on HUMAN proteins (Homo sapiens), not viral, bacterial, or other organism proteins
        - All UniProt IDs must be for human proteins
        - For infectious diseases (HIV, flu, etc.), suggest HUMAN host proteins involved in the disease
        
        For each protein, provide:
        1. Protein name
        2. UniProt ID (must be human protein)
        3. Why it's relevant to the query
        4. Brief function description
        5. Known drugs targeting it (if any)
        
        Format your response as a JSON array:
        [
            {
                "name": "Protein name",
                "uniprot_id": "P12345",
                "relevance": "Why this protein is a good target",
                "function": "What this protein does",
                "drugs": "Known drugs (or None)"
            }
        ]
        
        After the JSON array, add a summary starting with "INSIGHTS:" explaining the drug discovery strategy.
        """
        prompt = f"{system_prompt}\n\nUser Query: {prompt}\n\nResponse:"
    
    for attempt_model in fallback_models:
        try:
            print(f"🔄 Trying model: {attempt_model}")
            
            response = None
            
            # Method 1: Try conversational API
            try:
                response = request_client.conversational(
                    text=prompt,
                    model=attempt_model,
                    max_tokens=500,
                    temperature=0.7
                )
                if response and hasattr(response, 'generated_text'):
                    response = response.generated_text
                elif response and isinstance(response, dict) and 'generated_text' in response:
                    response = response['generated_text']
                print(f"✅ Conversational API succeeded for {attempt_model}")
            except Exception as conv_error:
                print(f"⚠️ Conversational failed: {str(conv_error)[:100]}")
                
                # Method 2: Try chat_completion
                try:
                    messages = [{"role": "user", "content": prompt}]
                    chat_response = request_client.chat_completion(
                        messages=messages,
                        model=attempt_model,
                        max_tokens=500,
                        temperature=0.7
                    )
                    response = chat_response.choices[0].message.content
                    print(f"✅ Chat completion succeeded for {attempt_model}")
                except Exception as chat_error:
                    print(f"⚠️ Chat completion failed: {str(chat_error)[:100]}")
                    
                    # Method 3: Try text_generation
                    try:
                        if "flan-t5" in attempt_model.lower():
                            response = request_client.text_generation(
                                f"Answer this question: {prompt}",
                                model=attempt_model,
                                max_new_tokens=500,
                                temperature=0.7,
                                return_full_text=False
                            )
                        else:
                            response = request_client.text_generation(
                                prompt,
                                model=attempt_model,
                                max_new_tokens=500,
                                temperature=0.7,
                                return_full_text=False
                            )
                        print(f"✅ Text generation succeeded for {attempt_model}")
                    except Exception as text_error:
                        print(f"⚠️ Text generation failed: {str(text_error)[:100]}")
                        response = None
            
            # Process response
            if response:
                text = response.strip() if isinstance(response, str) else str(response).strip()
                if text.startswith(prompt):
                    text = text[len(prompt):].strip()
                
                if len(text) > 10:
                    print(f"✅ Success with model: {attempt_model}")
                    return text
                
        except Exception as e:
            print(f"⚠️ Error with {attempt_model}: {str(e)[:150]}")
            if attempt_model == fallback_models[-1]:
                break
            continue
    
    print("❌ All fallback models exhausted")
    return "FALLBACK_NEEDED"

def parse_ai_response(response_text):
    """Parse AI response to extract protein targets"""
    proteins = []
    insights = ""
    
    json_match = re.search(r'\[[\s\S]*?\]', response_text)
    if json_match:
        try:
            proteins = json.loads(json_match.group())
        except:
            pass
    
    insights_match = re.search(r'INSIGHTS?:(.*?)(?:\n\n|\Z)', response_text, re.DOTALL | re.IGNORECASE)
    if insights_match:
        insights = insights_match.group(1).strip()
    
    return proteins, insights

def fallback_protein_extraction(text):
    """Fallback method - ONLY USED WHEN AI COMPLETELY FAILS"""
    if not DISEASE_PROTEIN_DATABASE:
        print("⚠️ Fallback database not loaded")
        return None
    
    text_lower = text.lower()
    
    # Search through disease database
    for disease, protein_list in DISEASE_PROTEIN_DATABASE.items():
        if disease in text_lower:
            print(f"📚 Using fallback database for disease: {disease}")
            return protein_list
    
    print("⚠️ No match found in fallback database")
    return None

def get_uniprot_info(uniprot_id):
    """Get protein information from UniProt"""
    try:
        url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                'name': data.get('proteinDescription', {}).get('recommendedName', {}).get('fullName', {}).get('value', 'Unknown'),
                'organism': data.get('organism', {}).get('scientificName', 'Unknown'),
                'length': data.get('sequence', {}).get('length', 0),
                'function': data.get('comments', [{}])[0].get('texts', [{}])[0].get('value', 'No description available')[:200]
            }
    except:
        pass
    return None

def generate_demo_structure():
    """Generate a simple demo PDB structure for visualization"""
    pdb_lines = ["HEADER    DEMO PROTEIN STRUCTURE"]
    pdb_lines.append("TITLE     DEMONSTRATION PROTEIN STRUCTURE")
    pdb_lines.append("REMARK    This is a simplified demonstration structure")
    
    atom_num = 1
    residue_num = 1
    
    import math
    for i in range(50):
        angle = i * 100
        radius = 2.3
        rise = 1.5
        
        x = radius * math.cos(math.radians(angle))
        y = radius * math.sin(math.radians(angle))
        z = i * rise
        
        pdb_lines.append(
            f"ATOM  {atom_num:5d}  CA  ALA A{residue_num:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 50.00           C"
        )
        atom_num += 1
        residue_num += 1
    
    pdb_lines.append("END")
    return "\n".join(pdb_lines)

def get_alphafold_structure(uniprot_id):
    """Get protein structure from AlphaFold Database"""
    try:
        url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v4.pdb"
        response = requests.get(url, timeout=15)
        if response.status_code == 200 and len(response.text) > 100:
            return response.text
        
        url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v3.pdb"
        response = requests.get(url, timeout=15)
        if response.status_code == 200 and len(response.text) > 100:
            return response.text
        
        uniprot_url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
        uniprot_response = requests.get(uniprot_url, timeout=10)
        
        if uniprot_response.status_code == 200:
            uniprot_data = uniprot_response.json()
            cross_refs = uniprot_data.get('uniProtKBCrossReferences', [])
            pdb_ids = [ref['id'] for ref in cross_refs if ref.get('database') == 'PDB']
            
            if pdb_ids:
                pdb_id = pdb_ids[0]
                pdb_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
                pdb_response = requests.get(pdb_url, timeout=10)
                if pdb_response.status_code == 200 and len(pdb_response.text) > 100:
                    return pdb_response.text
        
        search_url = "https://search.rcsb.org/rcsbsearch/v2/query"
        query = {
            "query": {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                    "operator": "exact_match",
                    "value": uniprot_id
                }
            },
            "return_type": "entry",
            "request_options": {"return_all_hits": False}
        }
        
        search_response = requests.post(search_url, json=query, timeout=10)
        if search_response.status_code == 200:
            results = search_response.json()
            if results.get('result_set') and len(results['result_set']) > 0:
                pdb_id = results['result_set'][0]['identifier']
                pdb_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
                pdb_response = requests.get(pdb_url, timeout=10)
                if pdb_response.status_code == 200 and len(pdb_response.text) > 100:
                    return pdb_response.text
                    
    except Exception as e:
        print(f"Error fetching structure for {uniprot_id}: {e}")
    
    return generate_demo_structure()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.json
        prompt = data.get('prompt', '')
        model = data.get('model', 'mistralai/Mistral-7B-Instruct-v0.3')
        hf_token = data.get('hf_token', '')
        
        if not prompt:
            return jsonify({'error': 'Please provide a research query'}), 400
        
        # Try AI first
        ai_response = query_huggingface(prompt, model, hf_token if hf_token else None)
        
        # Only use fallback if AI completely failed
        if ai_response == "FALLBACK_NEEDED":
            print("⚠️ AI models unavailable, using fallback database")
            proteins = fallback_protein_extraction(prompt)
            if not proteins:
                return jsonify({
                    'no_results': True,
                    'message': 'No proteins found in quick search'
                })
            insights = "AI models unavailable. Using curated human protein targets from database."
            return jsonify({
                'proteins': proteins,
                'ai_insights': insights,
                'model_used': 'fallback_database'
            })
        
        # Try to parse AI response
        proteins, insights = parse_ai_response(ai_response)

        # Filter to only keep human proteins using UniProt data
        filtered = []
        for p in proteins:
            uid = p.get("uniprot_id", "")
            if uid:
                info = get_uniprot_info(uid)
                if info and "Homo sapiens" in info.get("organism", ""):
                    p.update(info)
                    filtered.append(p)
        
        proteins = filtered

        # Only use fallback if AI returned nothing
        if not proteins:
            print("⚠️ AI returned no proteins, using fallback database")
            proteins = fallback_protein_extraction(prompt)
            if not proteins:
                return jsonify({
                    'no_results': True,
                    'message': 'No proteins found'
                })
            insights = insights or "Using curated human protein targets from database."
        
        # Enrich with UniProt data
        for protein in proteins:
            if protein.get('uniprot_id'):
                uniprot_info = get_uniprot_info(protein['uniprot_id'])
                if uniprot_info:
                    protein.update(uniprot_info)
        
        return jsonify({
            'proteins': proteins,
            'ai_insights': insights,
            'model_used': model
        })
        
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

@app.route('/get_structure', methods=['POST'])
def get_structure():
    try:
        data = request.json
        uniprot_id = data.get('uniprot_id', '')
        
        if not uniprot_id:
            return jsonify({'error': 'UniProt ID required'}), 400
        
        pdb_data = get_alphafold_structure(uniprot_id)
        uniprot_info = get_uniprot_info(uniprot_id)
        
        is_demo = pdb_data and 'DEMO PROTEIN STRUCTURE' in pdb_data
        
        response_data = {
            'uniprot_id': uniprot_id,
            'pdb_data': pdb_data,
            'length': uniprot_info.get('length', 'Unknown') if uniprot_info else 'Unknown',
            'organism': uniprot_info.get('organism', 'Unknown') if uniprot_info else 'Unknown',
            'confidence': 'Demo Structure' if is_demo else ('High (AlphaFold prediction)' if 'alphafold' in pdb_data.lower() else 'Experimental (PDB)'),
            'info': f"{'[DEMO] ' if is_demo else ''}{uniprot_info.get('function', 'Structure visualization') if uniprot_info else 'Showing demonstration protein structure.'}"
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({'error': f'Failed to load structure: {str(e)}'}), 500

@app.route('/deep_search', methods=['POST'])
def deep_search():
    """Deep search using UniProt API"""
    try:
        data = request.json
        query = data.get('query', '')
        
        if not query:
            return jsonify({'error': 'Query required'}), 400
        
        stop_words = ['protein', 'sequence', 'for', 'the', 'a', 'an', 'of', 'in', 'to', 'and', 'or', 'related', 'associated', 'with']
        keywords = []
        for word in query.lower().split():
            if word not in stop_words and len(word) > 2:
                keywords.append(word)
        
        if not keywords:
            keywords = [query]
        
        search_queries = [
            ' '.join(keywords),
            keywords[0] if keywords else query,
            f"{' '.join(keywords)} AND human",
        ]
        
        proteins = []
        
        for search_term in search_queries:
            search_url = f"https://rest.uniprot.org/uniprotkb/search?query=({search_term})+AND+organism_id:9606&size=5&format=json"
            
            try:
                response = requests.get(search_url, timeout=10)
                
                if response.status_code == 200:
                    uniprot_data = response.json()
                    results = uniprot_data.get('results', [])
                    
                    if results:
                        for entry in results[:5]:
                            primary_accession = entry.get('primaryAccession', '')
                            protein_desc = entry.get('proteinDescription', {})
                            recommended_name = protein_desc.get('recommendedName', {})
                            full_name = recommended_name.get('fullName', {}).get('value', 'Unknown Protein')
                            
                            if full_name == 'Unknown Protein':
                                alt_names = protein_desc.get('alternativeNames', [])
                                if alt_names:
                                    full_name = alt_names[0].get('fullName', {}).get('value', 'Unknown Protein')
                            
                            organism = entry.get('organism', {}).get('scientificName', 'Unknown')
                            sequence_info = entry.get('sequence', {})
                            seq_length = sequence_info.get('length', 0)
                            
                            function_text = 'Function information pending'
                            comments = entry.get('comments', [])
                            for comment in comments:
                                if comment.get('commentType') == 'FUNCTION':
                                    texts = comment.get('texts', [])
                                    if texts:
                                        function_text = texts[0].get('value', function_text)[:300]
                                    break
                            
                            relevance = f"Found in UniProt database for query related to {' '.join(keywords)}. This protein may be therapeutically relevant."
                            
                            disease_comments = [c for c in comments if c.get('commentType') == 'DISEASE']
                            if disease_comments:
                                disease_info = []
                                for dc in disease_comments:
                                    disease = dc.get('disease', {})
                                    disease_name = disease.get('description', '')
                                    if disease_name:
                                        disease_info.append(disease_name)
                                if disease_info:
                                    relevance = f"Associated with: {', '.join(disease_info[:2])}"
                            
                            proteins.append({
                                'name': full_name,
                                'uniprot_id': primary_accession,
                                'relevance': relevance,
                                'function': function_text,
                                'organism': organism,
                                'length': seq_length,
                                'drugs': 'Check clinical databases for therapeutic agents targeting this protein'
                            })
                        
                        if proteins:
                            break
            except:
                continue
        
        if not proteins:
            broad_search = f"https://rest.uniprot.org/uniprotkb/search?query={keywords[0] if keywords else query}+AND+reviewed:true&size=5&format=json"
            try:
                response = requests.get(broad_search, timeout=10)
                if response.status_code == 200:
                    uniprot_data = response.json()
                    results = uniprot_data.get('results', [])
                    
                    for entry in results[:3]:
                        primary_accession = entry.get('primaryAccession', '')
                        protein_desc = entry.get('proteinDescription', {})
                        recommended_name = protein_desc.get('recommendedName', {})
                        full_name = recommended_name.get('fullName', {}).get('value', 'Unknown Protein')
                        
                        organism = entry.get('organism', {}).get('scientificName', 'Unknown')
                        sequence_info = entry.get('sequence', {})
                        seq_length = sequence_info.get('length', 0)
                        
                        proteins.append({
                            'name': full_name,
                            'uniprot_id': primary_accession,
                            'relevance': f"Related to {keywords[0] if keywords else query} (reviewed entry)",
                            'function': 'Click to load more details',
                            'organism': organism,
                            'length': seq_length,
                            'drugs': 'Information available after loading structure'
                        })
            except:
                pass
        
        if not proteins:
            return jsonify({
                'proteins': [],
                'message': f"No results found. Try searching for specific protein names or medical conditions."
            })
        
        return jsonify({
            'proteins': proteins,
            'source': 'UniProt Deep Search',
            'search_term': ' '.join(keywords)
        })
        
    except Exception as e:
        return jsonify({'error': f'Deep search failed: {str(e)}'}), 500

@app.route('/chat_question', methods=['POST'])
def chat_question():
    """Handle protein Q&A and deep search questions"""

    import time

    try:
        data = request.json
        prompt = data.get('prompt', '')
        model = data.get('model', 'mistralai/Mistral-7B-Instruct-v0.3')
        hf_token = data.get('hf_token', '')

        if not prompt:
            return jsonify({'error': 'Prompt required'}), 400

        # Use global client or create new one if user token provided
        if hf_token and hf_token != DEFAULT_HF_TOKEN:
            request_client = InferenceClient(token=hf_token)
        else:
            request_client = client

        # Detect mode
        is_protein_qa = "You are a biomedical expert explaining the protein:" in prompt

        # Prepare fallback models
        fallback_models = [
            model,
            "meta-llama/Llama-3.2-3B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3",
            "HuggingFaceH4/zephyr-7b-beta",
            "microsoft/Phi-3-mini-4k-instruct",
            "google/flan-t5-large",
            "tiiuae/falcon-7b-instruct"
        ]
        
        # Remove duplicates
        seen = set()
        fallback_models = [m for m in fallback_models if not (m in seen or seen.add(m))]

        # Add biomedical context
        if "You are a biomedical" not in prompt:
            system_prompt = (
                "You are a biomedical AI assistant specialized in protein structure, "
                "molecular biology, and drug discovery. Provide clear, accurate answers "
                "to scientific questions. Keep responses short and factual."
            )
            prompt = f"{system_prompt}\n\nUser Query:\n{prompt}\n\nResponse:"

        response_text = None
        used_model = None

        # Try multiple models
        for m in fallback_models:
            print(f"[INFO] Attempting model: {m}")
            try:
                max_tokens = 500
                
                # Try Method 1: conversational API
                try:
                    response_text = request_client.conversational(
                        text=prompt,
                        model=m,
                        max_tokens=max_tokens,
                        temperature=0.7
                    )
                    if response_text and hasattr(response_text, 'generated_text'):
                        response_text = response_text.generated_text
                    elif response_text and isinstance(response_text, dict):
                        response_text = response_text.get('generated_text', str(response_text))
                    print(f"[SUCCESS] Conversational succeeded for {m}")
                except Exception as conv_error:
                    print(f"[WARN] Conversational failed: {str(conv_error)[:80]}")
                    
                    # Try Method 2: chat_completion
                    try:
                        messages = [{"role": "user", "content": prompt}]
                        chat_response = request_client.chat_completion(
                            messages=messages,
                            model=m,
                            max_tokens=max_tokens,
                            temperature=0.7
                        )
                        response_text = chat_response.choices[0].message.content
                        print(f"[SUCCESS] Chat completion succeeded for {m}")
                    except Exception as chat_error:
                        print(f"[WARN] Chat failed: {str(chat_error)[:80]}")
                        
                        # Try Method 3: text_generation
                        if "flan-t5" in m.lower():
                            response_text = request_client.text_generation(
                                f"Answer this question: {prompt}",
                                model=m,
                                max_new_tokens=max_tokens,
                                temperature=0.7,
                                return_full_text=False
                            )
                        else:
                            response_text = request_client.text_generation(
                                prompt,
                                model=m,
                                max_new_tokens=max_tokens,
                                temperature=0.7,
                                return_full_text=False
                            )
                        print(f"[SUCCESS] Text generation succeeded for {m}")
                
                # Process response
                if response_text:
                    text = response_text.strip() if isinstance(response_text, str) else str(response_text).strip()
                    # Remove prompt echo
                    if text.startswith(prompt):
                        text = text[len(prompt):].strip()
                    
                    if len(text) > 10:
                        used_model = m
                        print(f"[SUCCESS] Response received from {m}")
                        response_text = text
                        break
                        
            except Exception as e:
                print(f"[WARN] Model {m} failed: {str(e)[:100]}")
                time.sleep(1)
                continue

        # If all models failed
        if not response_text:
            if is_protein_qa:
                response_text = (
                    "The AI models are currently unavailable. Please try again in a few minutes."
                )
            else:
                response_text = (
                    "Could you clarify your question a bit more so I can find better results?"
                )

        return jsonify({
            'response': response_text,
            'model_used': used_model or "fallback"
        })

    except Exception as e:
        return jsonify({'error': f'Chat failed: {str(e)}'}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False) 