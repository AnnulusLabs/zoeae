use std::collections::HashMap;
use std::sync::RwLock;

/// Hemolymph. Open circulatory shared state. Thread-safe.
pub struct Blood { cells: RwLock<HashMap<String, String>> }

impl Blood {
    pub fn new() -> Self { Self { cells: RwLock::new(HashMap::new()) } }
    pub fn pump(&self, key: &str, val: &str) { self.cells.write().unwrap().insert(key.into(), val.into()); }
    pub fn draw(&self, key: &str) -> Option<String> { self.cells.read().unwrap().get(key).cloned() }
    pub fn flow(&self) -> HashMap<String, String> { self.cells.read().unwrap().clone() }
    pub fn len(&self) -> usize { self.cells.read().unwrap().len() }
}
