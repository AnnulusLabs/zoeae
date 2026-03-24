use crate::Detection;

/// 7-channel sensory array. Gaussian bleed between adjacent channels.
pub struct Antenna { bleed: f64, damping: [f64; 7] }

impl Antenna {
    pub fn new(damping: &[f64; 7], bleed: f64) -> Self {
        Self { bleed, damping: *damping }
    }

    pub fn process(&self, raw: &[f64; 7]) -> Detection {
        let mut out = [0.0f64; 7];
        for i in 0..7 {
            let mut v = raw[i] * self.damping[i];
            for j in 0..7 {
                if i != j {
                    let dist = (i as f64 - j as f64).abs();
                    let kernel = (-dist * dist / (2.0 * self.bleed * self.bleed)).exp();
                    v += raw[j] * kernel * self.damping[j];
                }
            }
            out[i] = v;
        }
        let total: f64 = out.iter().sum();
        if total > 0.0 { out.iter_mut().for_each(|v| *v /= total); }
        let (dominant, &max_v) = out.iter().enumerate().max_by(|a, b| a.1.partial_cmp(b.1).unwrap()).unwrap();
        let sharpness = if total > 0.0 { max_v } else { 0.0 };
        let overlap = 1.0 - out.iter().map(|v| v * v).sum::<f64>().sqrt();
        Detection { dominant, sharpness, channels: out, overlap }
    }
}
