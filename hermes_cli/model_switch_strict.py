"""Fail-closed selection for providers whose catalog defines exact identity."""


def route_strict_model_input(st):
    """Resolve before global aliases, MoA presets, or provider detection can intervene."""
    from hermes_cli.route_pin import validate_selection

    try:
        validate_selection(st.target_provider, st.new_model)
    except (RuntimeError, ValueError) as error:
        return st.fail_on_target(str(error))
    st.resolved_alias = ""
    return None
