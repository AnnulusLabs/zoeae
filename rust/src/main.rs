use zoeae::{Genome, Zoeae};

fn main() {
    let genome = Genome::new("zoeae-rs")
        .with_damping([1.0, 0.9, 0.8, 1.1, 0.7, 0.85, 1.0])
        .with_purpose("orchestrate");

    let mut z = Zoeae::hatch(genome);

    println!("zoeae v{}", env!("CARGO_PKG_VERSION"));
    println!("{:?} | bleed: {}", z.instar, z.instar.bleed());

    let d = z.perceive("hello world");
    println!("CH{} dominant | sharpness: {:.3} | overlap: {:.3}",
        d.dominant + 1, d.sharpness, d.overlap);

    while z.molt() {
        let d = z.perceive("hello world");
        println!("{:?} | bleed: {} | CH{} | sharpness: {:.3}",
            z.instar, z.instar.bleed(), d.dominant + 1, d.sharpness);
    }

    println!("\n{}", serde_json::to_string_pretty(&z.stats()).unwrap());
}
