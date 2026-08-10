// Companion type declaration for the plain-JS Navbar so the TypeScript
// build (noImplicitAny) can import it without a TS7016 error. Needed since
// the marketing layout (a .tsx file) now renders this same component —
// there is one nav for the whole site, and it lives in navbar.jsx.
// Runtime still uses navbar.jsx; this only supplies the type.
export declare function Navbar(props?: { embedded?: boolean }): any;
