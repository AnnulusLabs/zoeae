use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

/// Internal message.
#[derive(Debug, Clone)]
pub struct Signal { pub from: String, pub to: String, pub msg: String, pub t: u64 }

/// Ventral nerve cord. Inter-organ messaging bus.
pub struct Nerve {
    ganglia: Mutex<HashMap<String, VecDeque<Signal>>>,
    seq: Mutex<u64>,
}

impl Nerve {
    pub fn new() -> Self { Self { ganglia: Mutex::new(HashMap::new()), seq: Mutex::new(0) } }

    pub fn signal(&self, from: &str, to: &str, msg: &str) {
        let mut seq = self.seq.lock().unwrap();
        *seq += 1;
        let s = Signal { from: from.into(), to: to.into(), msg: msg.into(), t: *seq };
        self.ganglia.lock().unwrap().entry(to.into()).or_default().push_back(s);
    }

    pub fn broadcast(&self, from: &str, msg: &str) {
        let targets: Vec<String> = self.ganglia.lock().unwrap().keys().cloned().collect();
        for t in targets { self.signal(from, &t, msg); }
    }

    pub fn listen(&self, organ: &str) -> Vec<Signal> {
        self.ganglia.lock().unwrap().entry(organ.into()).or_default().drain(..).collect()
    }

    pub fn len(&self) -> usize {
        self.ganglia.lock().unwrap().values().map(|q| q.len()).sum()
    }
}
