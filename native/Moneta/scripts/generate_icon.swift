import AppKit

let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)
image.lockFocus()
let rect = NSRect(origin: .zero, size: size)
let background = NSBezierPath(roundedRect: rect.insetBy(dx: 28, dy: 28), xRadius: 220, yRadius: 220)
NSColor(calibratedRed: 0.055, green: 0.20, blue: 0.145, alpha: 1).setFill()
background.fill()
let ring = NSBezierPath(ovalIn: NSRect(x: 182, y: 182, width: 660, height: 660))
ring.lineWidth = 24
NSColor(calibratedRed: 0.85, green: 0.59, blue: 0.25, alpha: 1).setStroke()
ring.stroke()
let paragraph = NSMutableParagraphStyle()
paragraph.alignment = .center
let attributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 400, weight: .medium),
    .foregroundColor: NSColor(calibratedRed: 0.96, green: 0.95, blue: 0.90, alpha: 1),
    .paragraphStyle: paragraph,
]
NSAttributedString(string: "M", attributes: attributes).draw(in: NSRect(x: 180, y: 244, width: 664, height: 500))
image.unlockFocus()
guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) else { fatalError("Could not render Moneta icon") }
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
