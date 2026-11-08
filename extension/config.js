// Where this copy of the extension finds Dossier. This copy, from the repo, uses Dossier on this
// computer. The copy downloaded from the public site has this file replaced so it uses that site,
// signed in to the user's own account there (backend/app/extension_package.py, which also sets the
// manifest's host_permissions to match). If you run the backend on another port, change BACKEND
// here and the host_permissions in manifest.json.
export const HOSTED = false;
// The backend's API: the site checks.
export const BACKEND = "http://127.0.0.1:8000";
// The Dossier app: "scan yourself", sign-in, and private emails (with the user's session cookie).
export const APP_ORIGIN = "http://localhost:3000";
