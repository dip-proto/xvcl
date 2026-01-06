// Test: Include-once semantics (file included twice, should only appear once)
// Shared constants


// Should still only have one definition of constants
set req.http.X-Port = "8080";
