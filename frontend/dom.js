export const $ = (id) => document.getElementById(id);
/** Build nodes from untrusted filenames, answers and passages as plain text. */
export const element = (tag, text, className = "") => {
    const node = document.createElement(tag);
    // Never interpret uploaded content or model output as HTML.
    node.textContent = text;
    node.className = className;
    return node;
};
