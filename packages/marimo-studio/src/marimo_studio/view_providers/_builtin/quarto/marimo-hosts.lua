-- Keep paragraphs that hold only <marimo-cell> or <marimo-output> hosts as raw
-- HTML blocks. Pandoc otherwise wraps the hosts in <p>, which cannot contain
-- the block content Studio renders into them. Quarto hands filters a host's
-- start and end tags as one raw inline, and plain Pandoc hands them as two, so
-- the paragraph's raw HTML is matched as one string.
--
-- Pandoc reads an authored <span> or <div> as a native element and writes its
-- mo-value attribute back as data-mo-value. Hosts with mo-value are written
-- back as raw HTML with their attributes unchanged.

local HOSTS = { "marimo%-cell", "marimo%-output" }

local function after_host(text)
  for _, name in ipairs(HOSTS) do
    local rest = text:match("^%s*<" .. name .. "[%s>][^<]*</" .. name .. "%s*>(.*)$")
    if rest then
      return rest
    end
  end
  return nil
end

function Para(element)
  local markup = {}
  for _, item in ipairs(element.content) do
    if item.t == "RawInline" and item.format == "html" then
      table.insert(markup, item.text)
    elseif item.t == "Space" or item.t == "SoftBreak" then
      table.insert(markup, "\n")
    else
      return nil
    end
  end
  local text = table.concat(markup)
  -- HTML tag names ignore case, so match a lowercase copy and keep the markup.
  local rest = text:lower()
  repeat
    rest = after_host(rest)
    if rest == nil then
      return nil
    end
  until not rest:match("%S")
  return pandoc.RawBlock("html", text)
end

local function escape(value)
  return (value:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

local function start_tag(name, element)
  local tag = "<" .. name
  if element.identifier ~= "" then
    tag = tag .. ' id="' .. escape(element.identifier) .. '"'
  end
  if #element.classes > 0 then
    tag = tag .. ' class="' .. escape(table.concat(element.classes, " ")) .. '"'
  end
  for key, value in pairs(element.attributes) do
    tag = tag .. " " .. key .. '="' .. escape(value) .. '"'
  end
  return tag .. ">"
end

function Span(element)
  if element.attributes["mo-value"] == nil then
    return nil
  end
  local inlines = pandoc.List({ pandoc.RawInline("html", start_tag("span", element)) })
  inlines:extend(element.content)
  inlines:insert(pandoc.RawInline("html", "</span>"))
  return inlines
end

function Div(element)
  if element.attributes["mo-value"] == nil then
    return nil
  end
  local blocks = pandoc.List({ pandoc.RawBlock("html", start_tag("div", element)) })
  blocks:extend(element.content)
  blocks:insert(pandoc.RawBlock("html", "</div>"))
  return blocks
end
