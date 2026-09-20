# Agent guidelines for working in this config setup

## OS Support

I work in Arch Linux using Hyprland and macOS. We have bootstrap scripts for both that are routed based on that.
When installing or adding functionality that requires a certain library, ensure that both scripts are updated accordingly.
If there is something that is only linux spesific, like my Hyprland setup, then we only need to update the hyprland.txt for example or any of the others.

## Code and script guidelines

When writing code or scripts ensure that it follows the DRY and KISS prinsiples. DO not over engineer or over complicate things.

When a script or file exceeds 600 lines, it's time to split it up into smaller focused pieces. The same thing applies if the script has more than one responsibility.
Then you should make one entrypoint script and an accompanying folder.

### Do not overcomplicate

Why add many lines when few lines do trick?
The code should be compact, readable and not try to be fancy when it does not need to. Being fancy is a humans job.

### Code re-use

Do not re-invent the wheel. It is better to re-use existing functionality and adapt or use existing packages from the web or from the codebase than adding unessecary lines of code.
