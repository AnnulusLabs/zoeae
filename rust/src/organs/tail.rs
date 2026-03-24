use serde_json::Value;
use std::collections::HashMap;

/// Emergency response. Checkpoint + rollback + escape.
pub struct Tail { checkpoints: HashMap<String, Value> }

impl Tail {
    pub fn new() -> Self { Self { checkpoints: HashMap::new() } }

    pub fn checkpoint(&mut self, id: &str, state: Value) {
        self.checkpoints.insert(id.into(), state);
    }

    pub fn rollback(&self, id: &str) -> Option<&Value> {
        self.checkpoints.get(id)
    }

    pub fn snap(&self, reason: &str) {
        eprintln!("[TAIL SNAP] {}", reason);
        std::process::exit(1);
    }

    pub fn flick<F, T>(&mut self, id: &str, state: Value, f: F) -> Result<T, String>
    where F: FnOnce() -> Result<T, String> {
        self.checkpoint(id, state);
        match f() {
            Ok(v) => { self.checkpoints.remove(id); Ok(v) }
            Err(e) => Err(format!("rolled back {}: {}", id, e))
        }
    }
}
