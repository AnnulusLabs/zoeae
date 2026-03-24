/// Resource management. Breathes compute.
pub struct Gill { budget: f64, spent: f64, breaths: u64 }

impl Gill {
    pub fn new(budget: f64) -> Self { Self { budget, spent: 0.0, breaths: 0 } }

    pub fn breathe(&self, complexity: f64) -> &str {
        if complexity < 0.2 { "tiny" }
        else if complexity < 0.4 { "light" }
        else if complexity < 0.6 { "medium" }
        else if complexity < 0.8 { "heavy" }
        else { "massive" }
    }

    pub fn exhale(&mut self, cost: f64) { self.spent += cost; self.breaths += 1; }
    pub fn oxygen(&self) -> f64 { (self.budget - self.spent).max(0.0) }
    pub fn suffocating(&self) -> bool { self.oxygen() < self.budget * 0.05 }

    pub fn stats(&self) -> serde_json::Value {
        serde_json::json!({
            "budget": self.budget, "spent": self.spent,
            "remaining": self.oxygen(), "breaths": self.breaths,
        })
    }
}
