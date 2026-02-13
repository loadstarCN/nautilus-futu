pub mod client;
pub mod push_decode;

use pyo3::prelude::*;

/// Register the Python module.
pub fn register_module(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_class::<client::PyFutuClient>()?;
    Ok(())
}
