(async () => {
  const { initializeEditor } = await import("/editor-assets/editor/index.js");
  await initializeEditor();
})();
