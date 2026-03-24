/// Threat classification.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ThreatClass { Safe, Suspicious, Dangerous, Critical }

/// Structural security. Wraps every action. No bypass.
pub struct Exoskeleton {
    denied: Vec<String>,
    inspections: u64,
    blocks: u64,
}

impl Exoskeleton {
    pub fn new() -> Self {
        Self {
            denied: vec![
                "rm -rf /", "shutdown", "format", "mkfs", "dd if=",
                ":(){ :|:& };:", "> /dev/sd", "chmod -R 777 /",
            ].into_iter().map(String::from).collect(),
            inspections: 0, blocks: 0,
        }
    }

    pub fn inspect(&mut self, action: &str) -> ThreatClass {
        self.inspections += 1;
        let lower = action.to_lowercase();
        for d in &self.denied {
            if lower.contains(d) { self.blocks += 1; return ThreatClass::Critical; }
        }
        if lower.contains("sudo") || lower.contains("admin") { ThreatClass::Suspicious }
        else { ThreatClass::Safe }
    }

    pub fn guard<F, T>(&mut self, action: &str, f: F) -> Result<T, String>
    where F: FnOnce() -> T {
        match self.inspect(action) {
            ThreatClass::Critical => Err(format!("blocked: {}", action)),
            ThreatClass::Dangerous => Err(format!("dangerous: {}", action)),
            _ => Ok(f()),
        }
    }

    pub fn stats(&self) -> (u64, u64) { (self.inspections, self.blocks) }
}
