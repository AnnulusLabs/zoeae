use crate::{Genome, Zoeae};
use rand::Rng;

/// Reproduction. Creates children with inherited genome + mutations.
pub struct Spawn { pub lineage: Vec<String> }

impl Spawn {
    pub fn new() -> Self { Self { lineage: Vec::new() } }

    pub fn reproduce(&mut self, parent: &Zoeae, mutation_rate: f64) -> Zoeae {
        let mut rng = rand::thread_rng();
        let mut child_damping = parent.genome.damping;
        for d in &mut child_damping {
            if rng.r#gen::<f64>() < mutation_rate {
                *d = (*d + rng.r#gen_range(-0.2..0.2)).clamp(0.01, 2.0);
            }
        }
        let child_genome = Genome {
            name: format!("{}_child_{}", parent.genome.name, self.lineage.len()),
            damping: child_damping,
            purpose: parent.genome.purpose.clone(),
        };
        self.lineage.push(child_genome.name.clone());
        Zoeae::hatch(child_genome)
    }
}
