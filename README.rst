This is initial code for a server to accept scans from HP digital sender
scanners (e.g. HP9100c).

This is loosely based on nsjtpd (a Ruby implementation):
http://rubyforge.org/projects/nsjtpd/

and this initial version was written using the Twisted FTP protocol code
as reference (this is my first project using Twisted, and this version is also
partially to learn its interface).

Presently it's a quick-and-dirty implementation that will accept scanned
documents and header files and write them to temp files, but the code isn't
very well written (especially some of the code to deal with delays when
setting up data connections) and there's a lot of polishing to do.

