return {
  {
    "mfussenegger/nvim-jdtls",
    ft = "java",
    dependencies = { "mfussenegger/nvim-dap" },
    -- Actual start/attach lives in ftplugin/java.lua so FileType fires correctly
  },
}
