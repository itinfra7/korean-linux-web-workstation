local window_class = get_window_class() or ""
local window_role = get_window_role() or ""
local window_type = get_window_type() or ""

if window_class == "thunderbird_thunderbird" and window_role == "3pane" and window_type == "WINDOW_TYPE_NORMAL" then
    undecorate_window()
end
