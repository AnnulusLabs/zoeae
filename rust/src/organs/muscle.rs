use rayon::prelude::*;

/// Parallel compute. Flexes when heavy work is needed.
pub struct Muscle { cores: usize }

impl Muscle {
    pub fn new() -> Self { Self { cores: rayon::current_num_threads() } }

    pub fn flex<T, F>(&self, tasks: Vec<F>) -> Vec<T>
    where F: Fn() -> T + Send + Sync, T: Send {
        tasks.into_par_iter().map(|f| f()).collect()
    }

    pub fn flex_map<T, R, F>(&self, items: Vec<T>, f: F) -> Vec<R>
    where T: Send, R: Send, F: Fn(T) -> R + Send + Sync {
        items.into_par_iter().map(f).collect()
    }

    pub fn cores(&self) -> usize { self.cores }
}
