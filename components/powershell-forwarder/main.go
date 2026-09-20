// SPDX-License-Identifier: GPL-3.0-or-later
// Forward Windows PowerShell invocations to the installed Microsoft PowerShell.
// No profiles, logging, query stubs or command rewriting.
package main

import (
 "os"
 "os/exec"
 "path/filepath"
 "strings"
)

func main() {
 root := os.Getenv("ProgramW6432")
 if root == "" { root = os.Getenv("ProgramFiles") }
 if root == "" { os.Exit(2) }
 args := os.Args[1:]
 noProfile := false
 for _, arg := range args {
  if strings.EqualFold(arg, "-NoProfile") || strings.EqualFold(arg, "-NoP") { noProfile = true }
 }
 if !noProfile { args = append([]string{"-NoProfile"}, args...) }
 cmd := exec.Command(filepath.Join(root, "PowerShell", "7", "pwsh.exe"), args...)
 cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
 cmd.Env = append(os.Environ(), "POWERSHELL_UPDATECHECK=Off", "POWERSHELL_TELEMETRY_OPTOUT=1")
 if err := cmd.Run(); err != nil {
  if result, ok := err.(*exec.ExitError); ok { os.Exit(result.ExitCode()) }
  os.Exit(1)
 }
}
