use std::fs;

/// A chewed fragment of data.
#[derive(Debug, Clone)]
pub struct Fragment { pub content: String, pub source: String, pub nutritional_value: f64 }

/// Data ingestion. Eats files and text, chews into fragments.
pub struct Mouth { chunk_size: usize }

impl Mouth {
    pub fn new(bleed: f64) -> Self {
        Self { chunk_size: (500.0 + bleed * 1500.0) as usize }
    }

    pub fn eat(&self, path: &str) -> Vec<Fragment> {
        match fs::read_to_string(path) {
            Ok(text) => self.chew(&text, path),
            Err(_) => vec![],
        }
    }

    pub fn eat_text(&self, text: &str) -> Vec<Fragment> { self.chew(text, "<direct>") }

    fn chew(&self, text: &str, source: &str) -> Vec<Fragment> {
        text.as_bytes().chunks(self.chunk_size).map(|chunk| {
            let s = String::from_utf8_lossy(chunk).to_string();
            let nv = self.nutritional_value(&s);
            Fragment { content: s, source: source.into(), nutritional_value: nv }
        }).collect()
    }

    fn nutritional_value(&self, text: &str) -> f64 {
        let words: Vec<&str> = text.split_whitespace().collect();
        if words.is_empty() { return 0.0; }
        let unique: std::collections::HashSet<&str> = words.iter().copied().collect();
        unique.len() as f64 / words.len() as f64
    }
}
