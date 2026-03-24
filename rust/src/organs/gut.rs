use super::mouth::Fragment;
use std::collections::HashMap;

/// Extracted knowledge from digested fragments.
#[derive(Debug, Clone)]
pub struct Knowledge {
    pub entities: Vec<String>,
    pub facts: HashMap<String, String>,
}

/// Hepatopancreas. Digests fragments into structured knowledge.
pub struct Gut { absorbed: Vec<Knowledge> }

impl Gut {
    pub fn new() -> Self { Self { absorbed: Vec::new() } }

    pub fn digest(&self, fragments: &[Fragment]) -> Knowledge {
        let mut entities = Vec::new();
        let mut facts = HashMap::new();
        for frag in fragments {
            for word in frag.content.split_whitespace() {
                let w = word.trim_matches(|c: char| !c.is_alphanumeric());
                if w.len() > 1 && w.chars().next().map_or(false, |c| c.is_uppercase()) {
                    entities.push(w.to_string());
                }
            }
            if frag.nutritional_value > 0.5 {
                facts.insert(frag.source.clone(), format!("nv={:.2}", frag.nutritional_value));
            }
        }
        entities.sort(); entities.dedup();
        Knowledge { entities, facts }
    }

    pub fn absorb(&mut self, k: Knowledge) { self.absorbed.push(k); }

    pub fn excrete(&mut self) { self.absorbed.retain(|k| !k.entities.is_empty()); }

    pub fn memory_size(&self) -> usize { self.absorbed.len() }
}
