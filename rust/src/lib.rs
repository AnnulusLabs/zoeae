pub mod organs;

use organs::*;
use serde::{Deserialize, Serialize};
use std::time::Instant;

/// Developmental stage. Bleed narrows as the organism matures.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub enum Instar { I, II, III, IV, Megalopa }

impl Instar {
    pub fn bleed(&self) -> f64 {
        match self { Self::I => 0.85, Self::II => 0.60, Self::III => 0.35, Self::IV => 0.15, Self::Megalopa => 0.10 }
    }
    pub fn next(&self) -> Option<Self> {
        match self { Self::I => Some(Self::II), Self::II => Some(Self::III), Self::III => Some(Self::IV), Self::IV => Some(Self::Megalopa), Self::Megalopa => None }
    }
}

/// Detection result from antenna perception.
#[derive(Debug, Clone, Serialize)]
pub struct Detection {
    pub dominant: usize,
    pub sharpness: f64,
    pub channels: [f64; 7],
    pub overlap: f64,
}

/// The environment. Nothing exists without an ocean.
#[derive(Debug)]
pub struct Ocean {
    pub name: String,
    stimuli: Vec<String>,
    born: Instant,
}

impl Ocean {
    pub fn new(name: &str) -> Self {
        Self { name: name.into(), stimuli: Vec::new(), born: Instant::now() }
    }
    pub fn inject(&mut self, stimulus: &str) { self.stimuli.push(stimulus.into()); }
    pub fn age_secs(&self) -> f64 { self.born.elapsed().as_secs_f64() }
}

/// Triple-helix genome with developmental gating.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Genome {
    pub name: String,
    pub damping: [f64; 7],
    pub purpose: String,
}

impl Genome {
    pub fn new(name: &str) -> Self {
        Self { name: name.into(), damping: [1.0; 7], purpose: String::new() }
    }
    pub fn with_damping(mut self, d: [f64; 7]) -> Self { self.damping = d; self }
    pub fn with_purpose(mut self, p: &str) -> Self { self.purpose = p.into(); self }
}

/// The organism. Hatches into an ocean. Perceives. Develops. Molts.
pub struct Zoeae {
    pub genome: Genome,
    pub instar: Instar,
    pub antenna: Antenna,
    pub exo: Exoskeleton,
    pub nerve: Nerve,
    pub blood: Blood,
    pub gill: Gill,
    pub heart: Heart,
    trail: Vec<Detection>,
}

impl Zoeae {
    pub fn hatch(genome: Genome) -> Self {
        let bleed = Instar::I.bleed();
        Self {
            antenna: Antenna::new(&genome.damping, bleed),
            exo: Exoskeleton::new(),
            nerve: Nerve::new(),
            blood: Blood::new(),
            gill: Gill::new(10.0),
            heart: Heart::new(),
            genome,
            instar: Instar::I,
            trail: Vec::new(),
        }
    }

    pub fn perceive(&mut self, signal: &str) -> Detection {
        let raw: [f64; 7] = std::array::from_fn(|i| {
            let base = if i == 0 { signal.len() as f64 } else { (signal.as_bytes().get(i).copied().unwrap_or(0) as f64) / 255.0 };
            base * self.genome.damping[i]
        });
        let d = self.antenna.process(&raw);
        self.trail.push(d.clone());
        self.blood.pump("last_detection", &serde_json::to_string(&d).unwrap_or_default());
        d
    }

    pub fn molt(&mut self) -> bool {
        if let Some(next) = self.instar.next() {
            self.instar = next;
            self.antenna = Antenna::new(&self.genome.damping, next.bleed());
            true
        } else { false }
    }

    pub fn stats(&self) -> serde_json::Value {
        serde_json::json!({
            "name": self.genome.name,
            "instar": format!("{:?}", self.instar),
            "bleed": self.instar.bleed(),
            "trail_len": self.trail.len(),
            "gill": self.gill.stats(),
            "nerve_signals": self.nerve.len(),
            "blood_keys": self.blood.len(),
        })
    }
}
