// This device-only probe checks the SUSFS stat path after entering an app UID.
// Build with: GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o test-app-uid-stat ./scripts/test-app-uid-stat.go
package main

import (
	"fmt"
	"os"
	"strconv"
	"syscall"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "Usage: test-app-uid-stat UID PATH")
		os.Exit(2)
	}
	uid, err := strconv.Atoi(os.Args[1])
	if err != nil || uid < 0 {
		fmt.Fprintln(os.Stderr, "Invalid UID.")
		os.Exit(2)
	}
	if uid != os.Getuid() {
		if err := syscall.Setresuid(uid, uid, uid); err != nil {
			fmt.Fprintf(os.Stderr, "Setresuid failed: %v\n", err)
			os.Exit(2)
		}
	}
	var stat syscall.Stat_t
	statErr := syscall.Stat(os.Args[2], &stat)
	fmt.Printf("uid=%d\n", os.Getuid())
	if statErr != nil {
		fmt.Printf("stat_errno=%d\n", statErr.(syscall.Errno))
		os.Exit(1)
	}
	fmt.Printf("stat_size=%d\nstat_ino=%d\n", stat.Size, stat.Ino)
}
