-- The marimo shortcode places a notebook result in a Quarto document:
--
--   {{< marimo cell="summary" >}}       a complete notebook cell
--   {{< marimo output="chart" >}}       a cell's rendered output
--   {{< marimo value="metrics.total" >}} a JSON value in running text
--
-- An output shortcode may add accept="image/svg+xml image/png". Studio reads it
-- from the source and shows the output as the first listed image type the
-- value supports.
--
-- Studio adds a data-marimo-studio-site parameter to each shortcode in its
-- build snapshot, and the host keeps it so the browser can bind the result.

local HOSTS = {
  cell = { tag = "marimo-cell", attribute = "name" },
  output = { tag = "marimo-output", attribute = "value" },
}

local function text(value)
  if value == nil then
    return ""
  end
  return pandoc.utils.stringify(value)
end

local function escape(value)
  return (value:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

local function site(kwargs)
  local id = text(kwargs["data-marimo-studio-site"])
  if id == "" then
    return ""
  end
  return ' data-marimo-studio-site="' .. escape(id) .. '"'
end

return {
  marimo = function(_args, kwargs, _meta, _raw_args, context)
    for kind, host in pairs(HOSTS) do
      local target = text(kwargs[kind])
      if target ~= "" then
        local html = "<" .. host.tag .. " " .. host.attribute .. '="' .. escape(target) .. '"'
          .. site(kwargs) .. "></" .. host.tag .. ">"
        if context == "block" then
          return pandoc.RawBlock("html", html)
        end
        return pandoc.RawInline("html", html)
      end
    end
    local value = text(kwargs.value)
    if value ~= "" then
      local html = pandoc.RawInline("html", '<span mo-value="' .. escape(value) .. '"' .. site(kwargs) .. "></span>")
      -- A value alone in a block, such as a table cell, stays unwrapped.
      if context == "block" then
        return pandoc.Plain({ html })
      end
      return html
    end
    return quarto.shortcode.error_output("marimo", "needs cell, output, or value", context)
  end,
}
