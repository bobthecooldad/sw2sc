//! sw2sc: a clean-room SolidWorks part reader that writes SolidCraft designs with their feature
//! tree. A Rust port of the Python package `sw2sc`, which stays the reference: every module here
//! names the one it ports, and the tests compare the two on the sample parts.

pub mod cfb;
pub mod swfile;
pub mod archive;
pub mod design;
pub mod features;
pub mod pyfmt;
pub mod verify;
pub mod fillets;
pub mod search;
#[cfg(not(target_arch = "wasm32"))]
pub mod cli;
pub mod nurbs;
pub mod parasolid;
pub mod xtgeom;
pub mod step;
pub mod convert;
