/// Goal state.
#[derive(Debug, Clone, PartialEq)]
pub enum GoalState { Planning, Swimming, Drifting, Arrived, Failed }

/// A goal being pursued.
#[derive(Debug, Clone)]
pub struct Goal { pub objective: String, pub state: GoalState, pub steps: Vec<String>, pub progress: usize }

/// Pleopods. Active goal pursuit.
pub struct Swim { goals: Vec<Goal> }

impl Swim {
    pub fn new() -> Self { Self { goals: Vec::new() } }

    pub fn toward(&mut self, objective: &str, steps: Vec<String>) -> usize {
        let id = self.goals.len();
        self.goals.push(Goal {
            objective: objective.into(), state: GoalState::Planning,
            steps, progress: 0,
        });
        id
    }

    pub fn stroke(&mut self, id: usize) -> Option<&str> {
        let g = self.goals.get_mut(id)?;
        if g.progress >= g.steps.len() { g.state = GoalState::Arrived; return None; }
        g.state = GoalState::Swimming;
        let step = g.steps[g.progress].as_str();
        g.progress += 1;
        Some(step)
    }

    pub fn arrive(&mut self, id: usize) { if let Some(g) = self.goals.get_mut(id) { g.state = GoalState::Arrived; } }
    pub fn fail(&mut self, id: usize) { if let Some(g) = self.goals.get_mut(id) { g.state = GoalState::Failed; } }
    pub fn active(&self) -> Vec<&Goal> { self.goals.iter().filter(|g| g.state == GoalState::Swimming).collect() }
}
