use std::time::Instant;

/// The pump. Heartbeat tracking + uptime.
pub struct Heart { born: Instant, beats: u64 }

impl Heart {
    pub fn new() -> Self { Self { born: Instant::now(), beats: 0 } }
    pub fn beat(&mut self) { self.beats += 1; }
    pub fn bpm(&self) -> f64 {
        let secs = self.born.elapsed().as_secs_f64();
        if secs > 0.0 { self.beats as f64 / secs * 60.0 } else { 0.0 }
    }
    pub fn uptime_secs(&self) -> f64 { self.born.elapsed().as_secs_f64() }
    pub fn beats(&self) -> u64 { self.beats }
}
