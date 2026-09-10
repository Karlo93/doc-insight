export const $ = (id) => document.getElementById(id);
export const element = (tag, text, className = "") => {
    const node = document.createElement(tag);
    node.textContent = text;
    node.className = className;
    return node;
};
