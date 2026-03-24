use std::collections::HashMap;
use std::time::Instant;

/// Defensive spines. Rate limiting + abuse detection.
pub struct Shell {
    hits: HashMap<String, Vec<Instant>>,
    blocked: HashMap<String, Instant>,
    rate_limit: usize,     // max hits per window
    window_secs: f64,
}

impl Shell {
    pub fn new(rate_limit: usize, window_secs: f64) -> Self {
        Self { hits: HashMap::new(), blocked: HashMap::new(), rate_limit, window_secs }
    }

    pub fn spike(&mut self, source: &str) -> bool {
        if let Some(until) = self.blocked.get(source) {
            if until.elapsed().as_secs_f64() < self.window_secs { return false; }
            self.blocked.remove(source);
        }
        let now = Instant::now();
        let entry = self.hits.entry(source.into()).or_default();
        entry.retain(|t| t.elapsed().as_secs_f64() < self.window_secs);
        entry.push(now);
        if entry.len() > self.rate_limit {
            self.blocked.insert(source.into(), now);
            return false;
        }
        true
    }

    pub fn shed(&mut self) { self.hits.clear(); self.blocked.clear(); }
}
