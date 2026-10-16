pub trait Engine {
    fn run(&self);
}

pub struct TurboEngine {
    pub power: u32,
}

impl Engine for TurboEngine {
    fn run(&self) {
        println!("Running at power {}", self.power);
    }
}
