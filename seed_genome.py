"""Seed the AUTONOMY genome with AnnulusLabs core knowledge."""
import sys
sys.path.insert(0, r'C:\Users\slows\.openclaw\workspace')
from autonomy import *

engine = get_engine()

nodes = [
    GenomeNode(id='kerf', node_type=NodeType.PRINCIPLE, content='The kerf is the 27-degree gap where the circle remains broken to vibrate - fundamental axiom of Completionary Mathematics', domain='mathematics'),
    GenomeNode(id='tcs', node_type=NodeType.FACT, content='Cancer is a voltage-gated chirality phase transition via CISS - membrane depolarization past -25mV shifts surface CCM from L-biological toward achiral midpoint', domain='biology'),
    GenomeNode(id='ciss', node_type=NodeType.FACT, content='CISS effect: electron transport through chiral molecules is spin-selective and conformation-dependent (Naaman-Waldeck)', domain='physics'),
    GenomeNode(id='hedgehog', node_type=NodeType.ARTIFACT, content='Hedgehog Hash: 7 Klein bottles, S_7 symmetric group, 36288-bit security via topological non-invertibility', domain='cryptography'),
    GenomeNode(id='postprompt', node_type=NodeType.PRINCIPLE, content='Post-Prompting: minimal stress prompts maximize Information Delta by forcing model to traverse latent space', domain='ai'),
    GenomeNode(id='prometheus', node_type=NodeType.ARTIFACT, content='PROMETHEUS-K: volumetric confinement fusion via amplituhedron positive geometry with 7 fuzzy logarithmic facets', domain='physics'),
    GenomeNode(id='nox', node_type=NodeType.ARTIFACT, content='NOX: sovereign AI framework - 350+ modules, 260K+ lines, cavity-resonant inference, gene evolution', domain='ai'),
    GenomeNode(id='tdna', node_type=NodeType.ARTIFACT, content='TDNA: ternary gene architecture with spiral phase evolution for real-time adaptive control', domain='ai'),
    GenomeNode(id='autonomy_sys', node_type=NodeType.ARTIFACT, content='AUTONOMY v3.0: sovereign cognitive agent with triple-helix genome, StressCompiler, CRDT sync, because-chains', domain='ai'),
    GenomeNode(id='annulusos', node_type=NodeType.ARTIFACT, content='AnnulusOS: bare-metal OS for AI - no Linux, no Windows, ARM64 port active', domain='systems'),
    GenomeNode(id='kerf_comms', node_type=NodeType.ARTIFACT, content='KERF: sovereign comms framework - 94 files, patent-pending, cavity-native protocol', domain='communications', private=True),
    GenomeNode(id='ccm_avnir', node_type=NodeType.FACT, content='Avnir CCM: quantifies chirality on continuous scale, L-biological cluster ~90, achiral midpoint ~50', domain='biology'),
    GenomeNode(id='alpatov', node_type=NodeType.FACT, content='Alpatov 1950: malignant tissue inverted chirality sensitivity - CIA classified CONFIDENTIAL 1951', domain='biology'),
    GenomeNode(id='roncevic', node_type=NodeType.FACT, content='Roncevic 2026: half-Mobius C13Cl2 voltage-switchable chirality, 0.26 eV switching energy', domain='physics'),
    GenomeNode(id='cone', node_type=NodeType.FACT, content='Cone 1971: depolarization threshold -25mV where mitotic control is lost', domain='biology'),
    GenomeNode(id='info_delta', node_type=NodeType.PRINCIPLE, content='Information Delta Law: novel output = I(response) - I(prompt), maximized at load-bearing minimum', domain='ai'),
]

edges = [
    GenomeEdge(source_id='tcs', target_id='kerf', edge_type=EdgeType.BRIDGES, because='cancer cells drift into the chirality kerf via CISS-mediated voltage bias', metadata={'domain_a':'biology','domain_b':'mathematics'}),
    GenomeEdge(source_id='tcs', target_id='ciss', edge_type=EdgeType.DEPENDS, because='CISS provides the physical mechanism bridging voltage to surface chirality'),
    GenomeEdge(source_id='tcs', target_id='ccm_avnir', edge_type=EdgeType.DEPENDS, because='Avnir CCM quantifies the chirality shift TCS predicts'),
    GenomeEdge(source_id='tcs', target_id='alpatov', edge_type=EdgeType.DEPENDS, because='Alpatov 1950 is the founding observation of inverted chirality in malignancy'),
    GenomeEdge(source_id='tcs', target_id='roncevic', edge_type=EdgeType.DEPENDS, because='Roncevic 2026 proves electronic chirality is voltage-switchable'),
    GenomeEdge(source_id='tcs', target_id='cone', edge_type=EdgeType.DEPENDS, because='Cone 1971 established the -25mV threshold TCS identifies as chirality transition'),
    GenomeEdge(source_id='hedgehog', target_id='kerf', edge_type=EdgeType.BRIDGES, because='Klein bottles have no interior boundary - kerf principle applied to crypto topology', metadata={'domain_a':'cryptography','domain_b':'mathematics'}),
    GenomeEdge(source_id='prometheus', target_id='kerf', edge_type=EdgeType.BRIDGES, because='reactor spirals 73 degrees past 360, leaving 27-degree kerf as resonant cavity', metadata={'domain_a':'physics','domain_b':'mathematics'}),
    GenomeEdge(source_id='prometheus', target_id='tdna', edge_type=EdgeType.DEPENDS, because='TDNA gene evolution controls 7 confinement facets via spiral phase'),
    GenomeEdge(source_id='nox', target_id='tdna', edge_type=EdgeType.DEPENDS, because='NOX uses TDNA for gene-evolved learning instead of gradient descent'),
    GenomeEdge(source_id='postprompt', target_id='info_delta', edge_type=EdgeType.IMPLIES, because='Post-Prompting is the practical application of the Information Delta Law'),
    GenomeEdge(source_id='postprompt', target_id='kerf', edge_type=EdgeType.BRIDGES, because='detailed prompts eliminate best answers by constraining past the kerf', metadata={'domain_a':'ai','domain_b':'mathematics'}),
    GenomeEdge(source_id='autonomy_sys', target_id='nox', edge_type=EdgeType.DEPENDS, because='AUTONOMY is the cognitive persistence layer for NOX'),
    GenomeEdge(source_id='autonomy_sys', target_id='postprompt', edge_type=EdgeType.DEPENDS, because='StressCompiler implements Post-Prompting as tiered context injection'),
    GenomeEdge(source_id='kerf_comms', target_id='kerf', edge_type=EdgeType.BRIDGES, because='KERF comms uses kerf principle for sovereign cavity-native protocol', metadata={'domain_a':'communications','domain_b':'mathematics'}),
]

sid = engine.session_id
for n in nodes:
    engine.genome.add_node(n, sid)
for e in edges:
    engine.genome.add_edge(e, sid)

engine.genome.compute_load_bearing()
engine.genome.save()

s = engine.genome.stats()
print(f"Nodes: {s['total_nodes']} ({s['active']} active, {s['load_bearing']} LB)")
print(f"Edges: {s['edges']} ({s['edges_with_because']} because, {s['because_coverage']})")
print(f"Domains: {s['domains']} {s['domain_list']}")
print(f"Bridges: {s['bridges']}")

lb = [n for n in engine.genome.nodes.values() if n.load_bearing]
print(f"\nLoad-bearing nodes:")
for n in lb:
    print(f"  * [{n.domain}] {n.id}: {n.content[:80]}")

# Test StressCompiler at each tier
compiler = StressCompiler(engine.genome)
for t in range(4):
    compiled = compiler.compile(tier=t)
    tokens = len(compiled) // 4
    print(f"\nTier {t}: ~{tokens} tokens")
    if t == 0:
        print(compiled)

# Verify append log
valid, count, msg = engine.log.verify_chain()
print(f"\nAppend log: {'VALID' if valid else 'BROKEN'} ({msg})")
