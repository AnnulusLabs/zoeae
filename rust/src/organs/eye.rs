/// A detected threat.
#[derive(Debug, Clone)]
pub struct Threat { pub source: String, pub severity: f64, pub pattern: String }

/// Compound eye. Pattern recognition + threat detection.
pub struct Eye { facets: usize }

impl Eye {
    pub fn new(bleed: f64) -> Self {
        Self { facets: (3.0 + (1.0 - bleed) * 20.0) as usize }
    }

    pub fn scan(&self, environment: &std::collections::HashMap<String, String>) -> Vec<Threat> {
        let patterns = ["error", "fail", "panic", "crash", "denied", "timeout", "overflow"];
        let mut threats = Vec::new();
        for (key, val) in environment {
            let lower = format!("{} {}", key, val).to_lowercase();
            for &p in &patterns {
                if lower.contains(p) {
                    threats.push(Threat {
                        source: key.clone(),
                        severity: if p == "panic" || p == "crash" { 0.9 } else { 0.5 },
                        pattern: p.into(),
                    });
                }
            }
        }
        threats
    }

    pub fn facets(&self) -> usize { self.facets }
}
