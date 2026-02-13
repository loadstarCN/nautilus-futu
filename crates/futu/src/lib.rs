pub mod config;
pub mod protocol;
pub mod client;
pub mod quote;
pub mod trade;
pub mod python;

// Re-export generated protobuf types
pub mod generated;

use pyo3::prelude::*;

/// The Futu OpenD adapter Python module.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<python::client::PyFutuClient>()?;
    Ok(())
}
